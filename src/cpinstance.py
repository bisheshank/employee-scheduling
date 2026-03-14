from __future__ import annotations

import math
import sys
import json
from collections import defaultdict
from typing import Optional, List, Tuple

from ortools.constraint_solver import pywrapcp

# ========== CONSTRAINT FLAGS (for incremental testing) ==========
# Core constraints (required by spec)
ENABLE_TABLE_CONSTRAINTS = True  # (shift, hours) validity links
ENABLE_TRAINING = True  # AllDifferent for first 4 days
ENABLE_DEMAND = True  # Distribute for minDemandDayShift
ENABLE_MIN_DAILY_OPERATION = True  # Sum of hours >= minDailyOperation
ENABLE_WEEKLY_HOURS = True  # BetweenCt for min/max weekly
ENABLE_NIGHT_CONSECUTIVE = True  # Sliding window for maxConsecutiveNightShift
ENABLE_NIGHT_TOTAL = True  # Total night shift limit

# Redundant constraints (implied, for stronger propagation)
ENABLE_SYMMETRY_BREAKING = True  # Lexicographic employee ordering
ENABLE_REDUNDANT_MAX_OFF = True  # Upper bound on off-shifts per day
ENABLE_TOTAL_HORIZON = True  # Global min/max hours over entire period
ENABLE_IMPLIED_WORKING_DAYS = True  # Min/max working days per employee

# Search strategy flags
IS_DEFAULT = False  # Use DefaultPhase (vs custom Phase)
IS_TIGHT = False  # Tight mode: deterministic, fail-first
IS_RESTART = False  # Use LubyRestart for exploration
IS_DAY_PHASE = True

# Ethical/Employee-friendly flags
# When ETHICAL_OFF_FIRST=True, OFF_SHIFT=0 so ASSIGN_MIN_VALUE tries off-shifts
# first, giving employees more rest days. When False, OFF_SHIFT=4 so working
# shifts (1,2,3) are preferred, maximizing productivity.

# NOTE: in this same spirit maybe reorganizing the shift preferring day shifts first would
# give better propoagation
ETHICAL_OFF_FIRST = False  # Prefer giving employees days off
# When ENABLE_POST_PROCESS=True, start times are evenly distributed within each
# shift to spread out coverage. When False, everyone starts at shift start time.
ENABLE_POST_PROCESS = True  # Even spread of start times within shifts
# =================================================================


class CPInstance:
    # BUSINESS parameters
    numWeeks: int
    numDays: int
    numEmployees: int
    numShifts: int
    numIntervalsInDay: int
    minDemandDayShift: list[list[int]]
    minDailyOperation: int

    # EMPLOYEE parameters
    minConsecutiveWork: int
    maxDailyWork: int
    minWeeklyWork: int
    maxWeeklyWork: int
    maxConsecutiveNightShift: int
    maxTotalNightShift: int

    # Solver & Shift Constants
    solver: pywrapcp.Solver
    OFF_SHIFT: int
    WORKING_SHIFTS: list[int]

    def __init__(self, filename: str):
        self.filename = filename

        # Define our shift constants
        # OFF_SHIFT=0: off-shifts tried first with ASSIGN_MIN_VALUE (employee-friendly)
        # OFF_SHIFT=4: working shifts (1,2,3) tried first (productivity-focused)
        self.OFF_SHIFT = 0 if ETHICAL_OFF_FIRST else 4
        self.WORKING_SHIFTS = [1, 2, 3]  # Night, Day, Evening

        self.load_from_file(filename)
        self.solver = None

    def load_from_file(self, f: str):
        """
        Reads in a file and populates the instance parameters.
        """
        params = {}
        if not f:
            print("No file provided")
            return
        with open(f, "r") as fl:
            lines = fl.readlines()
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("Business_"):
                    key, value = line.split(":")
                    if key != "Business_minDemandDayShift":
                        params[key] = int(value)
                    else:
                        params[key] = [int(x) for x in value.split()]
                elif line.startswith("Employee_"):
                    key, value = line.split(":")
                    params[key] = int(value)

        self.numWeeks = params.get("Business_numWeeks")
        self.numDays = params.get("Business_numDays")
        self.numEmployees = params.get("Business_numEmployees")
        self.numShifts = params.get("Business_numShifts")
        self.numIntervalsInDay = params.get("Business_numIntervalsInDay")

        raw = params.get("Business_minDemandDayShift", [])
        self.minDemandDayShift = []
        if raw:
            for i in range(0, self.numDays * self.numShifts, self.numShifts):
                self.minDemandDayShift.append(raw[i: i + self.numShifts])

        self.minDailyOperation = params.get("Business_minDailyOperation")
        self.minConsecutiveWork = params.get("Employee_minConsecutiveWork")
        self.maxDailyWork = params.get("Employee_maxDailyWork")
        self.minWeeklyWork = params.get("Employee_minWeeklyWork")
        self.maxWeeklyWork = params.get("Employee_maxWeeklyWork")
        self.maxConsecutiveNightShift = params.get(
            "Employee_maxConsecutiveNigthShift")
        self.maxTotalNightShift = params.get("Employee_maxTotalNigthShift")

    def _precompute_tuples(self):
        """
        Pre-compute valid (shift, hours) pairs.
        Begin/end times are computed post-solution since no constraint depends on them.
        """
        # Off shift: no hours worked
        tuples = [(self.OFF_SHIFT, 0)]

        # Working shifts: hours range from minConsecutiveWork to maxDailyWork
        for shift_id in self.WORKING_SHIFTS:
            for h in range(self.minConsecutiveWork, self.maxDailyWork + 1):
                tuples.append((shift_id, h))

        return tuples

    def solve(self, time_limit_seconds: Optional[float] = None):
        """
        Employee Scheduling Model
        """
        # PRECOMPUTATION
        # Tuples are now (shift, hours) pairs - begin/end computed post-solution
        valid_tuples = self._precompute_tuples()
        valid_shifts = sorted({t[0] for t in valid_tuples})
        valid_hours = sorted({t[1] for t in valid_tuples})

        E = self.numEmployees
        D = self.numDays
        W = self.numWeeks

        # Shift start times for post-computation
        SHIFT_START = {1: 0, 2: 8, 3: 16}  # Night, Day, Evening

        # INITIALIZATION
        self.solver = pywrapcp.Solver("EmployeeScheduling")

        # VARIABLES (simplified: only shift and hours, no begin/end)
        shift = [
            [self.solver.IntVar(valid_shifts, f"s_{e}_{d}") for d in range(D)]
            for e in range(E)
        ]
        hours = [
            [self.solver.IntVar(valid_hours, f"h_{e}_{d}") for d in range(D)]
            for e in range(E)
        ]

        is_night = [
            [self.solver.IsEqualCstVar(shift[e][d], 1) for d in range(D)]
            for e in range(E)
        ]

        avg_forced = sum(
            sum(self.minDemandDayShift[d][s] for s in self.WORKING_SHIFTS)
            for d in range(D)
        ) / (D * E)

        # TABLE CONSTRAINTS (AllowedAssignments)
        # Links shift and hours via valid (shift, hours) pairs
        # if ENABLE_TABLE_CONSTRAINTS:
        #     for e in range(E):
        #         for d in range(D):
        #             self.solver.Add(
        #                 self.solver.AllowedAssignments(
        #                     [shift[e][d], hours[e][d]], valid_tuples
        #                 )
        #             )
        if ENABLE_TABLE_CONSTRAINTS:
            for e in range(E):
                for d in range(D):
                    self.solver.Add(
                        (shift[e][d] == self.OFF_SHIFT) == (hours[e][d] == 0)
                    )

        # SYMMETRY BREAKING
        # Force Employee e's entire 21+ day schedule to be lexicographically
        # less than or equal to Employee e+1's schedule.
        if ENABLE_SYMMETRY_BREAKING:
            sym_days = min(D, 14)
            for e in range(E - 1):
                self.solver.Add(
                    self.solver.LexicalLessOrEqual(
                        [shift[e][d] for d in range(sym_days)],
                        [shift[e+1][d] for d in range(sym_days)]
                    )
                )

        # TRAINING
        # AllDifferent for first 4 days - each employee experiences all shifts
        if ENABLE_TRAINING:
            for e in range(E):
                training_days = min(D, 4)
                if training_days > 1:
                    self.solver.Add(
                        self.solver.AllDifferent(
                            [shift[e][d] for d in range(training_days)]
                        )
                    )

        # DEMAND - Using Distribute (global cardinality constraint)
        if ENABLE_DEMAND:
            for d in range(D):
                day_shifts = [shift[e][d] for e in range(E)]
                # Values: Night=1, Day=2, Evening=3, Off=4
                values = [1, 2, 3, self.OFF_SHIFT]
                card_min = [
                    self.minDemandDayShift[d][1],  # Night demand
                    self.minDemandDayShift[d][2],  # Day demand
                    self.minDemandDayShift[d][3],  # Evening demand
                    0,  # Off (no minimum)
                ]
                card_max = [E, E, E, E]  # No upper limit on any shift
                self.solver.Add(
                    self.solver.Distribute(
                        day_shifts, values, card_min, card_max)
                )

        # MIN DAILY OPERATION
        if ENABLE_MIN_DAILY_OPERATION:
            for d in range(D):
                self.solver.Add(
                    self.solver.Sum([hours[e][d] for e in range(E)]) >= self.minDailyOperation
                )

        # WEEKLY HOURS - Using BetweenCt for cleaner constraint
        if ENABLE_WEEKLY_HOURS:
            for e in range(E):
                for w in range(W):
                    week_start = w * 7
                    if week_start + 7 <= D:
                        week_hours = [
                            hours[e][d] for d in range(week_start, week_start + 7)
                        ]
                        week_sum = self.solver.Sum(week_hours)
                        self.solver.Add(
                            self.solver.BetweenCt(
                                week_sum, self.minWeeklyWork, self.maxWeeklyWork
                            )
                        )

        # NIGHT SHIFTS - CONSECUTIVE
        if ENABLE_NIGHT_CONSECUTIVE:
            for e in range(E):
                window_size = self.maxConsecutiveNightShift + 1
                if window_size <= D:
                    for d in range(D - window_size + 1):
                        window = [is_night[e][d + i]
                                  for i in range(window_size)]
                        self.solver.Add(
                            self.solver.Sum(
                                window) <= self.maxConsecutiveNightShift
                        )

        # NIGHT SHIFTS - TOTAL
        if ENABLE_NIGHT_TOTAL:
            for e in range(E):
                self.solver.Add(self.solver.Sum(
                    is_night[e]) <= self.maxTotalNightShift)

        # REDUNDANT CONSTRAINTS - Max off-shifts per day
        if ENABLE_REDUNDANT_MAX_OFF:
            for d in range(D):
                min_workers_demand = sum(
                    self.minDemandDayShift[d][s] for s in self.WORKING_SHIFTS
                )
                min_workers_hours = math.ceil(
                    self.minDailyOperation / self.maxDailyWork
                )
                min_workers = max(min_workers_demand, min_workers_hours)
                max_off = E - min_workers
                if max_off >= 0 and max_off < E:
                    self.solver.Add(
                        self.solver.Sum(
                            [shift[e][d] == self.OFF_SHIFT for e in range(E)]
                        )
                        <= max_off
                    )

        # TOTAL HORIZON
        # NOTE: This seems to somewhat help 21 day cases
        if ENABLE_TOTAL_HORIZON:
            for e in range(E):
                employee_all_hours = [hours[e][d] for d in range(D)]

                # Constraints the total work over the whole period
                self.solver.Add(
                    self.solver.Sum(
                        employee_all_hours) >= self.minWeeklyWork * W
                )
                self.solver.Add(
                    self.solver.Sum(
                        employee_all_hours) <= self.maxWeeklyWork * W
                )

        # IMPLIED CONSTRAINTS: Min/Max working days per employee
        # Each employee must work a minimum number of days to meet weekly hours
        if ENABLE_IMPLIED_WORKING_DAYS:
            min_working_days = math.ceil(
                (self.minWeeklyWork * W) / self.maxDailyWork)
            max_working_days = min(
                D, (self.maxWeeklyWork * W) // self.minConsecutiveWork
            )

            for e in range(E):
                is_working = [shift[e][d] != self.OFF_SHIFT for d in range(D)]
                self.solver.Add(self.solver.Sum(
                    is_working) >= min_working_days)
                self.solver.Add(self.solver.Sum(
                    is_working) <= max_working_days)

        # SEARCH STRATEGY
        # Interleaved day phases: commit all employees for one day before moving
        # to the next. Fires Distribute demand and daily operation constraints
        # immediately per day, giving strong pruning for all instance types.
        value_selector = (
            self.solver.ASSIGN_MIN_VALUE if IS_TIGHT
            # else self.solver.ASSIGN_RANDOM_VALUE
            else self.solver.ASSIGN_MAX_VALUE
        )

        day_phases = []
        for d in range(D):
            day_shift_vars = [shift[e][d] for e in range(E)]
            day_hours_vars = [hours[e][d] for e in range(E)]
            day_phases.append(self.solver.Phase(
                day_shift_vars,
                self.solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
                value_selector,
            ))
            day_phases.append(self.solver.Phase(
                day_hours_vars,
                self.solver.CHOOSE_FIRST_UNBOUND,
                self.solver.ASSIGN_MIN_VALUE,
            ))
        db = self.solver.Compose(day_phases)

        # MONITORS & LIMITS
        monitors = []
        if IS_RESTART:
            if avg_forced < 0.15:
                # Loose instances: restart aggressively, many symmetric solutions exist
                monitors.append(self.solver.LubyRestart(50))
            else:
                # Use LubyRestarts for exploration (good for loose instances)
                monitors.append(self.solver.LubyRestart(100))

        if time_limit_seconds:
            monitors.append(self.solver.TimeLimit(
                int(time_limit_seconds * 1000)))

        # TODO: would this even work def BranchesLimit(self, branches):
        # Creates a search limit that constrains the number of branches explored in the search tree.

        # EXECUTE SEARCH
        self.solver.NewSearch(db, monitors)

        if self.solver.NextSolution():
            # Shift start times for computing begin/end
            SHIFT_START = {1: 0, 2: 8, 3: 16}  # Night, Day, Evening

            # Step 1: Extract raw solution (shift, hours) for each (employee, day)
            raw_solution = {}
            for e in range(E):
                for d in range(D):
                    raw_solution[(e, d)] = (
                        shift[e][d].Value(), hours[e][d].Value())

            # Step 2: Compute begin times
            begin_times = {}

            if ENABLE_POST_PROCESS:
                # POST-PROCESSING: Distribute start times evenly within each shift
                # Groups employees by (day, shift) and spreads their start times
                SHIFT_BOUNDS = {1: (0, 8), 2: (8, 16), 3: (16, 24)}

                groups = defaultdict(list)
                for (e, d), (shift_val, hours_val) in raw_solution.items():
                    if shift_val != self.OFF_SHIFT:
                        groups[(d, shift_val)].append((e, hours_val))

                for (d, shift_val), employees in groups.items():
                    shift_start, shift_end = SHIFT_BOUNDS[shift_val]
                    n = len(employees)

                    # Sort by hours worked (shorter shifts get later indices)
                    employees_sorted = sorted(employees, key=lambda x: x[1])

                    for i, (e, hours_val) in enumerate(employees_sorted):
                        max_start = shift_end - hours_val
                        range_size = max_start - shift_start

                        if n > 1 and range_size > 0:
                            offset = (i * range_size) // (n - 1)
                        else:
                            offset = 0

                        begin_times[(e, d)] = shift_start + offset
            else:
                # NO POST-PROCESSING: Everyone starts at shift start time
                for (e, d), (shift_val, hours_val) in raw_solution.items():
                    if shift_val != self.OFF_SHIFT:
                        begin_times[(e, d)] = SHIFT_START[shift_val]

            # Step 3: Build final schedule
            schedule = []
            for e in range(E):
                emp_schedule = []
                for d in range(D):
                    shift_val, hours_val = raw_solution[(e, d)]

                    if shift_val == self.OFF_SHIFT:
                        emp_schedule.append((-1, -1))
                    else:
                        begin_val = begin_times[(e, d)]
                        end_val = begin_val + hours_val
                        emp_schedule.append((begin_val, end_val))
                schedule.append(emp_schedule)

            return True, self.solver.Failures(), schedule
        else:
            return False, self.solver.Failures(), None

    def prettyPrint(self, numEmployees, numDays, sched):
        """
        Poor man's Gantt chart.
        Displays the employee schedules on the command line.
        """
        for e in range(numEmployees):
            print(f"E{e + 1}: ", end="")
            if e < 9:
                print(" ", end="")
            for d in range(numDays):
                begin = sched[e][d][0]
                end = sched[e][d][1]
                for i in range(self.numIntervalsInDay):
                    if i % 8 == 0:
                        print("|", end="")
                    if begin != end and i >= begin and i < end:
                        print("+", end="")
                    else:
                        print(".", end="")
                print("|", end="")
            print(" ")

    def generateVisualizerInput(self, numEmployees, numDays, sched):
        solString = f"{numDays} {numEmployees}\n"
        for d in range(numDays):
            for e in range(numEmployees):
                solString += f"{sched[e][d][0]} {sched[e][d][1]}\n"

        fileName = f"{numDays}_{numEmployees}_sol.txt"
        try:
            with open(fileName, "w") as fl:
                fl.write(solString)
            print(f"File created: {fileName}")
        except IOError as e:
            print(f"An error occured: {e}")