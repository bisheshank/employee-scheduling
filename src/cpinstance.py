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
        Pre-compute all the valid work tuples in the form of:
        (shift, begin, end, hours)
        """
        SHIFTS = [
            (1, "Night", 0, 8),
            (2, "Day", 8, 16),
            (3, "Evening", 16, 24)
        ]

        # Use our new OFF_SHIFT constant instead of 0
        tuples = [(self.OFF_SHIFT, 24, 24, 0)]

        for shift_id, _, shift_start, shift_end in SHIFTS:
            tuples += [
                (shift_id, begin, end, end - begin)
                for begin in range(shift_start,
                                   shift_end - self.minConsecutiveWork + 1)
                for end in range(begin + self.minConsecutiveWork,
                                 min(begin + self.maxDailyWork + 1, shift_end + 1))
            ]

        return tuples

    def solve(self, time_limit_seconds: Optional[float] = None):
        """
        Employee Scheduling Model
        """
        # PRECOMPUTATION
        valid_tuples = self._precompute_tuples()
        valid_shifts = sorted({t[0] for t in valid_tuples})
        valid_begins = sorted({t[1] for t in valid_tuples})
        valid_ends = sorted({t[2] for t in valid_tuples})
        valid_hours = sorted({t[3] for t in valid_tuples})

        E = self.numEmployees
        D = self.numDays
        W = self.numWeeks

        # INITIALIZATION
        self.solver = pywrapcp.Solver("EmployeeScheduling")

        # VARIABLES
        shift = [[self.solver.IntVar(valid_shifts, f"s_{e}_{
                                     d}") for d in range(D)] for e in range(E)]
        begin = [[self.solver.IntVar(valid_begins, f"b_{e}_{
                                     d}") for d in range(D)] for e in range(E)]
        end = [[self.solver.IntVar(
            valid_ends, f"e_{e}_{d}") for d in range(D)] for e in range(E)]
        hours = [[self.solver.IntVar(
            valid_hours, f"h_{e}_{d}") for d in range(D)] for e in range(E)]

        is_night = [
            [self.solver.IsEqualCstVar(shift[e][d], 1) for d in range(D)]
            for e in range(E)
        ]

        # TABLE CONSTRAINTS (AllowedAssignments)
        for e in range(E):
            for d in range(D):
                self.solver.Add(
                    self.solver.AllowedAssignments(
                        [shift[e][d], begin[e][d], end[e][d], hours[e][d]],
                        valid_tuples
                    )
                )

        # SYMMETRY BREAKING
        for e in range(E - 1):
            self.solver.Add(shift[e][0] <= shift[e + 1][0])

        # TRAINING
        training_days = min(D, 4)
        if training_days == 4:
            for e in range(E):
                s = shift[e]
                self.solver.Add(s[0] != s[1])
                self.solver.Add(s[0] != s[2])
                self.solver.Add(s[0] != s[3])
                self.solver.Add(s[1] != s[2])
                self.solver.Add(s[1] != s[3])
                self.solver.Add(s[2] != s[3])

        # for e in range(E):
        #     training_days = min(D, 4)
        #     if training_days > 1:
        #         self.solver.Add(
        #             self.solver.AllDifferent(
        #                 [shift[e][d] for d in range(training_days)]
        #             )
        #         )

        # DEMAND
        for d in range(D):
            for s in self.WORKING_SHIFTS:
                # Subtract 1 because shift IDs (1,2,3) are 1-indexed
                # but the demand list is 0-indexed.
                demand = self.minDemandDayShift[d][s - 1]
                if demand > 0:
                    self.solver.Add(
                        self.solver.Sum(
                            [shift[e][d] == s for e in range(E)]) >= demand
                    )

        # MIN DAILY OPERATION
        for d in range(D):
            self.solver.Add(
                self.solver.Sum([hours[e][d]
                                for e in range(E)]) >= self.minDailyOperation
            )

        # WEEKLY HOURS
        for e in range(E):
            for w in range(W):
                week_start = w * 7
                if week_start + 7 <= D:
                    week_hours = [hours[e][d]
                                  for d in range(week_start, week_start + 7)]
                    self.solver.Add(self.solver.Sum(week_hours)
                                    >= self.minWeeklyWork)
                    self.solver.Add(self.solver.Sum(week_hours)
                                    <= self.maxWeeklyWork)

        # NIGHT SHIFTS
        for e in range(E):
            window_size = self.maxConsecutiveNightShift + 1
            if window_size <= D:
                for d in range(D - window_size + 1):
                    window = [is_night[e][d + i] for i in range(window_size)]
                    self.solver.Add(self.solver.Sum(window) <=
                                    self.maxConsecutiveNightShift)

            self.solver.Add(self.solver.Sum(
                is_night[e]) <= self.maxTotalNightShift)

        # REDUNDANT CONSTRAINTS
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
                        [shift[e][d] == self.OFF_SHIFT for e in range(E)]) <= max_off
                )

        # TOTAL HORIZON
        for e in range(E):
            # Using the local variable 'hours' instead of 'self.hours'
            employee_all_hours = [hours[e][d] for d in range(D)]

            # Constraints the total work over the whole period
            self.solver.Add(self.solver.Sum(employee_all_hours)
                            >= self.minWeeklyWork * W)
            self.solver.Add(self.solver.Sum(employee_all_hours)
                            <= self.maxWeeklyWork * W)

        # Total hours across ALL employees for ALL days must meet the total min operation
        all_hours_in_system = [hours[e][d] for e in range(E) for d in range(D)]
        total_required_hours = self.minDailyOperation * D

        self.solver.Add(self.solver.Sum(all_hours_in_system)
                        >= total_required_hours)

        # SEARCH STRATEGY
        all_shift_vars = []
        all_time_vars = []

        # Group variables Employee-by-Employee so consecutive constraints fail fast
        for e in range(E):
            for d in range(D):
                all_shift_vars.append(shift[e][d])

        for e in range(E):
            for d in range(D):
                all_time_vars.extend([begin[e][d], end[e][d], hours[e][d]])

        # PHASE 1: Decide Shifts using ASSIGN_MIN_VALUE
        # Prefers 1, 2, 3 over OFF=4
        db_shifts = self.solver.Phase(
            all_shift_vars,
            self.solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
            self.solver.ASSIGN_RANDOM_VALUE
        )

        # PHASE 2: Decide Exact Times
        db_times = self.solver.Phase(
            all_time_vars,
            self.solver.CHOOSE_FIRST_UNBOUND,
            self.solver.ASSIGN_MIN_VALUE
        )

        db = self.solver.Compose([db_shifts, db_times])

        # MONITORS & LIMITS
        monitors = [self.solver.LubyRestart(800)]
        if time_limit_seconds:
            monitors.append(self.solver.TimeLimit(
                int(time_limit_seconds * 1000)))

        # EXECUTE SEARCH
        self.solver.NewSearch(db, monitors)

        if self.solver.NextSolution():
            schedule = [
                [
                    (-1, -1) if shift[e][d].Value() == self.OFF_SHIFT else (
                        begin[e][d].Value(), end[e][d].Value())
                    for d in range(D)
                ]
                for e in range(E)
            ]
            return True, self.solver.Failures(), schedule
        else:
            return False, self.solver.Failures(), None

    def prettyPrint(self, numEmployees, numDays, sched):
        """
        Poor man's Gantt chart.
        Displays the employee schedules on the command line. 
        """
        for e in range(numEmployees):
            print(f"E{e+1}: ", end="")
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
