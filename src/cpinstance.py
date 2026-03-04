from __future__ import annotations

import sys
from typing import Optional, List, Tuple

import numpy as np
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

    # Solver
    solver: pywrapcp.Solver

    def __init__(self, filename: str):
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

        tuples = [(0, 24, 24, 0)]  # Off shift added once

        for shift_id, _, shift_start, shift_end in SHIFTS:
            tuples += [
                (shift_id, begin, end, end - begin)
                for begin in range(shift_start,
                                   shift_end - self.minConsecutiveWork + 1)
                for end in range(begin + self.minConsecutiveWork,
                                 min(begin + self.maxDailyWork + 1, shift_end + 1))
            ]

        print(tuples)
        return tuples

    def solve(
        self,
        time_limit_seconds: Optional[float] = None,
    ):
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

        print(f"[Tuples]  {len(valid_tuples)} valid tuples precomputed")
        print(f"[Domains] shifts={valid_shifts}")
        print(f"[Domains] begins={valid_begins}")
        print(f"[Domains] ends  ={valid_ends}")
        print(f"[Domains] hours ={valid_hours}")
        print(f"[Model] {E} employees x {D} days = {E*D} table constraints")

        # INITIALIZATION
        self.solver = pywrapcp.Solver("EmployeeScheduling")

        # VARIABLES
        shift = [
            [
                self.solver.IntVar(valid_shifts, f"s_{e}_{d}")
                for d in range(D)
            ]
            for e in range(E)
        ]
        begin = [
            [
                self.solver.IntVar(valid_begins, f"b_{e}_{d}")
                for d in range(D)
            ]
            for e in range(E)
        ]
        end = [
            [
                self.solver.IntVar(valid_ends, f"e_{e}_{d}")
                for d in range(D)
            ]
            for e in range(E)
        ]
        hours = [
            [
                self.solver.IntVar(valid_hours, f"h_{e}_{d}")
                for d in range(D)
            ]
            for e in range(E)
        ]

        print(f"[Vars] {E*D*4} IntVars created ({E*D} per variable type)")

        # Allowed assignments from the precomputation
        for e in range(E):
            for d in range(D):
                self.solver.Add(
                    self.solver.AllowedAssignments(
                        [shift[e][d], begin[e][d], end[e][d], hours[e][d]],
                        valid_tuples
                    )
                )

        # CONSTRAINTS

        # Training
        for e in range(E):
            if D >= 4:  # What to do when < 4
                self.solver.Add(
                    self.solver.AllDifferent(
                        [shift[e][0], shift[e][1], shift[e][2], shift[e][3]]
                    )
                )

        # Demand
        for d in range(D):
            for s in range(1, self.numShifts):
                demand = self.minDemandDayShift[d][s]
                if demand > 0:
                    self.solver.Add(
                        # Count employees working shift s on day d
                        self.solver.Sum(
                            [shift[e][d] == s for e in range(E)]) >= demand
                    )

        # Minimum total hours per day
        for d in range(D):
            self.solver.Add(
                self.solver.Sum(
                    [hours[e][d] for e in range(E)]) >= self.minDailyOperation
            )

        # Weekly
        for e in range(E):
            for w in range(W):
                week_start = w * 7
                week_end = min(week_start + 7, D)
                week_hours = [hours[e][d] for d in range(week_start, week_end)]

                self.solver.Add(
                    self.solver.Sum(week_hours) >= self.minWeeklyWork
                )
                self.solver.Add(
                    self.solver.Sum(week_hours) <= self.maxWeeklyWork
                )

        # TODO: The precomputation effectively removes the need for mindailywork
        # Is this what we want?

        # Night shifts
        for e in range(E):
            is_night = [shift[e][d] == 1 for d in range(D)]

            for d in range(D - 1):
                self.solver.Add(
                    is_night[d] + is_night[d + 1]
                    <= self.maxConsecutiveNightShift
                )

            self.solver.Add(
                self.solver.Sum(is_night) <= self.maxTotalNightShift
            )

        # NOTE: Symmetry breaking to enforce a canonical lexicographic ordering
        # across employees.
        # This keeps only ONE representative solution per equivalence class.
        for e in range(E - 1):
            self.solver.Add(
                self.solver.LexicalLessOrEqual(shift[e], shift[e + 1])
            )

        # SEARCH SPACE
        all_vars = []
        for e in range(E):
            for d in range(D):
                all_vars.append(shift[e][d])
        for e in range(E):
            for d in range(D):
                all_vars.extend([begin[e][d], end[e][d]])

        # solve
        db = self.solver.DefaultPhase(all_vars)

        if time_limit_seconds:
            limit = self.solver.TimeLimit(
                int(time_limit_seconds * 1000)  # s to ms
            )
            self.solver.NewSearch(db, limit)
        else:
            self.solver.NewSearch(db)

        if self.solver.NextSolution():
            schedule = [
                [
                    (-1, -1) if shift[e][d].Value() == 0
                    else (begin[e][d].Value(), end[e][d].Value())
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
        Each row corresponds to a single employee. 
        A "+" refers to a working hour and "." means no work
        The shifts are separated with a "|"
        The days are separated with "||"

        This might help you analyze your solutions. 

        @param numEmployees the number of employees
        @param numDays the number of days
        @param sched sched[e][d] = (begin, end) hours for employee e on day d
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
