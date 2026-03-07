from __future__ import annotations

import math
import sys
import json
from typing import Optional, List, Tuple

from ortools.constraint_solver import pywrapcp


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
        # NOTE: This is making them work a lot
        # this might also be another count of --ethical flag
        self.OFF_SHIFT = 4
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
                self.minDemandDayShift.append(raw[i : i + self.numShifts])

        self.minDailyOperation = params.get("Business_minDailyOperation")
        self.minConsecutiveWork = params.get("Employee_minConsecutiveWork")
        self.maxDailyWork = params.get("Employee_maxDailyWork")
        self.minWeeklyWork = params.get("Employee_minWeeklyWork")
        self.maxWeeklyWork = params.get("Employee_maxWeeklyWork")
        self.maxConsecutiveNightShift = params.get("Employee_maxConsecutiveNigthShift")
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

        # TABLE CONSTRAINTS (AllowedAssignments)
        # Links shift and hours via valid (shift, hours) pairs
        for e in range(E):
            for d in range(D):
                self.solver.Add(
                    self.solver.AllowedAssignments(
                        [shift[e][d], hours[e][d]], valid_tuples
                    )
                )

        # # SYMMETRY BREAKING
        # for e in range(E - 1):
        #     self.solver.Add(shift[e][0] <= shift[e + 1][0])

        # Force Employee e's entire 21+ day schedule to be lexicographically
        # less than or equal to Employee e+1's schedule.
        for e in range(E - 1):
            employee_e_shifts = []
            employee_next_shifts = []

            # Gather the full horizon of shift variables for both employees
            for d in range(D):
                employee_e_shifts.append(shift[e][d])
                employee_next_shifts.append(shift[e + 1][d])

            # Apply the legacy CP solver's lexicographical constraint
            self.solver.Add(
                self.solver.LexicalLessOrEqual(employee_e_shifts, employee_next_shifts)
            )

        # TRAINING
        # TODO: would this be faster instead of alldifferent?
        # training_days = min(D, 4)
        # if training_days == 4:
        #     for e in range(E):
        #         s = shift[e]
        #         self.solver.Add(s[0] != s[1])
        #         self.solver.Add(s[0] != s[2])
        #         self.solver.Add(s[0] != s[3])
        #         self.solver.Add(s[1] != s[2])
        #         self.solver.Add(s[1] != s[3])
        #         self.solver.Add(s[2] != s[3])

        # Distribute
        # Overload 1: All variables are pairwise different. This corresponds to the stronger version of the propagation algorithm.
        #
        # |
        #
        # Overload 2: All variables are pairwise different. If 'stronger_propagation' is true, stronger, and potentially slower propagation will occur. This API will be deprecated in the future.
        for e in range(E):
            training_days = min(D, 4)
            if training_days > 1:
                self.solver.Add(
                    self.solver.AllDifferent(
                        [shift[e][d] for d in range(training_days)]
                    )
                )

        # DEMAND - Using Distribute (global cardinality constraint)
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
                self.solver.Distribute(day_shifts, values, card_min, card_max)
            )

        # MIN DAILY OPERATION
        for d in range(D):
            self.solver.Add(
                self.solver.Sum([hours[e][d] for e in range(E)])
                >= self.minDailyOperation
            )

        # WEEKLY HOURS - Using BetweenCt for cleaner constraint
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

        # NIGHT SHIFTS
        for e in range(E):
            # TODO: There must be something different we can do that here
            window_size = self.maxConsecutiveNightShift + 1
            if window_size <= D:
                for d in range(D - window_size + 1):
                    window = [is_night[e][d + i] for i in range(window_size)]
                    self.solver.Add(
                        self.solver.Sum(window) <= self.maxConsecutiveNightShift
                    )

            self.solver.Add(self.solver.Sum(is_night[e]) <= self.maxTotalNightShift)

        # REDUNDANT CONSTRAINTS
        for d in range(D):
            min_workers_demand = sum(
                self.minDemandDayShift[d][s] for s in self.WORKING_SHIFTS
            )
            min_workers_hours = math.ceil(self.minDailyOperation / self.maxDailyWork)
            min_workers = max(min_workers_demand, min_workers_hours)
            max_off = E - min_workers
            if max_off >= 0 and max_off < E:
                self.solver.Add(
                    self.solver.Sum([shift[e][d] == self.OFF_SHIFT for e in range(E)])
                    <= max_off
                )

        # TOTAL HORIZON
        # NOTE: This seems to somewhat help 21 day cases
        for e in range(E):
            employee_all_hours = [hours[e][d] for d in range(D)]

            # Constraints the total work over the whole period
            self.solver.Add(
                self.solver.Sum(employee_all_hours) >= self.minWeeklyWork * W
            )
            self.solver.Add(
                self.solver.Sum(employee_all_hours) <= self.maxWeeklyWork * W
            )

        # Total hours across ALL employees for ALL days must meet the total min operation
        all_hours_in_system = [hours[e][d] for e in range(E) for d in range(D)]
        total_required_hours = self.minDailyOperation * D

        self.solver.Add(self.solver.Sum(all_hours_in_system) >= total_required_hours)

        # IMPLIED CONSTRAINTS: Min/Max working days per employee
        # Each employee must work a minimum number of days to meet weekly hours
        min_working_days = math.ceil((self.minWeeklyWork * W) / self.maxDailyWork)
        max_working_days = min(D, (self.maxWeeklyWork * W) // self.minConsecutiveWork)

        for e in range(E):
            is_working = [shift[e][d] != self.OFF_SHIFT for d in range(D)]
            self.solver.Add(self.solver.Sum(is_working) >= min_working_days)
            self.solver.Add(self.solver.Sum(is_working) <= max_working_days)

        # NOTE: For now easy switch
        is_tight = False

        # SEARCH STRATEGY
        all_shift_vars = []
        all_hours_vars = []

        # Order by DAY first, then employee - helps demand constraints propagate
        for d in range(D):
            for e in range(E):
                all_shift_vars.append(shift[e][d])

        # Hours only (begin/end removed, computed post-solution)
        for d in range(D):
            for e in range(E):
                all_hours_vars.append(hours[e][d])

        all_vars = all_shift_vars + all_hours_vars

        # just for trying
        is_default = True

        if is_default:
            db = self.solver.DefaultPhase(
                all_vars,
                # self.solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
                # self.solver.ASSIGN_RANDOM_VALUE,
            )
        else:
            # TODO: Would impact based search heuristics help here??
            # PHASE 1: Decide Shifts dynamically based on tightness
            if is_tight:
                # Deterministic: Fail-first, assign smallest values (good for constrained spaces)
                db_shifts = self.solver.Phase(
                    all_shift_vars,
                    self.solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
                    self.solver.ASSIGN_MIN_VALUE,
                )
            else:
                # Randomized: Good for exploration in looser problem spaces
                db_shifts = self.solver.Phase(
                    all_shift_vars,
                    self.solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
                    self.solver.ASSIGN_RANDOM_VALUE,
                )

            # PHASE 2: Decide Hours
            db_times = self.solver.Phase(
                all_hours_vars,
                self.solver.CHOOSE_FIRST_UNBOUND,
                self.solver.ASSIGN_MIN_VALUE,
            )

            db = self.solver.Compose([db_shifts, db_times])

        # MONITORS & LIMITS
        monitors = []
        if not is_tight:
            # Only use LubyRestarts if we are randomly exploring (loose instances)
            monitors.append(self.solver.LubyRestart(100))

        if time_limit_seconds:
            monitors.append(self.solver.TimeLimit(int(time_limit_seconds * 1000)))

        # TODO: would this even work def BranchesLimit(self, branches):
        # Creates a search limit that constrains the number of branches explored in the search tree.

        # EXECUTE SEARCH
        self.solver.NewSearch(db, monitors)

        if self.solver.NextSolution():
            # POST-COMPUTATION: Derive begin/end from shift and hours
            schedule = []
            for e in range(E):
                emp_schedule = []
                for d in range(D):
                    shift_val = shift[e][d].Value()
                    hours_val = hours[e][d].Value()

                    if shift_val == self.OFF_SHIFT:
                        emp_schedule.append((-1, -1))
                    else:
                        begin_val = SHIFT_START[shift_val]
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
