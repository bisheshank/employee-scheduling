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
        self.solver = pywrapcp.Solver('employee_scheduling')

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


    def solve(
        self,
        time_limit_seconds: Optional[float] = None,
    ):
        """
        Employee Scheduling Model 
        """
    
        from itertools import permutations

        solver = self.solver
        E  = self.numEmployees
        D  = self.numDays
        W  = self.numWeeks
        S  = self.numShifts   # 4: off=0, night=1, day=2, evening=3

        SHIFT_START = [0, 0, 8, 16]
        SHIFT_END   = [0, 8, 16, 24]
        minC     = self.minConsecutiveWork
        maxD     = self.maxDailyWork
        TRAINING = min(4, D)

        # ── PRECOMPUTE POST-TRAINING TABLE ───────────────────────────────
        # Valid (shift, hours) pairs for post-training days.
        # Off last so ASSIGN_MIN_VALUE tries work shifts first.
        table = []
        for k in range(1, S):
            window = SHIFT_END[k] - SHIFT_START[k]  # always 8
            for h in range(minC, min(maxD, window) + 1):
                table.append((k, h))
        table.append((0, 0))  # off last

        N            = len(table)
        tbl_shift    = [row[0] for row in table]
        tbl_hours    = [row[1] for row in table]
        tbl_is_night = [1 if row[0] == 1 else 0 for row in table]
        tbl_is_k     = {
            k: [1 if row[0] == k else 0 for row in table]
            for k in range(1, S)
        }

        # ── PRECOMPUTE TRAINING PERMUTATIONS ────────────────────────────
        # 4! = 24 permutations of shift values {0,1,2,3}.
        # perm_shift[p][d] = shift assigned on training day d under permutation p.
        all_perms  = list(permutations(range(S)))
        P          = len(all_perms)                          # 24
        perm_shift = [[all_perms[p][d] for d in range(TRAINING)] for p in range(P)]

        # Precompute per-shift, per-day boolean lookup over permutations:
        # has_k_on_d[k][d][p] = 1 iff permutation p assigns shift k on training day d
        has_k_on_d = {
            k: [[1 if perm_shift[p][d] == k else 0 for p in range(P)]
                for d in range(TRAINING)]
            for k in range(1, S)
        }
        # is_night_on_d[d][p] = 1 iff permutation p assigns night on training day d
        is_night_on_d = [
            [1 if perm_shift[p][d] == 1 else 0 for p in range(P)]
            for d in range(TRAINING)
        ]

        # ── VARIABLES ────────────────────────────────────────────────────

        # Training: one permutation index per employee (domain 0..23)
        perm = [solver.IntVar(0, P - 1, f"perm_{e}") for e in range(E)]

        # Post-training: one table index per (employee, post-training day)
        idx = [
            [solver.IntVar(0, N - 1, f"idx_{e}_{d}") for d in range(D - TRAINING)]
            for e in range(E)
        ]

        # Training hours: free within [0, maxD], constrained below by shift type
        train_hours = [
            [solver.IntVar(0, maxD, f"th_{e}_{d}") for d in range(TRAINING)]
            for e in range(E)
        ]

        # ── DERIVED EXPRESSIONS (no search variables) ────────────────────

        # Training shift on day d for employee e = Element lookup into perm_shift column
        train_shift = [
            [solver.Element([perm_shift[p][d] for p in range(P)], perm[e])
            for d in range(TRAINING)]
            for e in range(E)
        ]

        # Training night indicator: 1 iff perm assigns night on day d
        train_is_night = [
            [solver.Element(is_night_on_d[d], perm[e]) for d in range(TRAINING)]
            for e in range(E)
        ]

        # Post-training derived expressions
        post_hours    = [[solver.Element(tbl_hours,    idx[e][d]) for d in range(D - TRAINING)] for e in range(E)]
        post_is_night = [[solver.Element(tbl_is_night, idx[e][d]) for d in range(D - TRAINING)] for e in range(E)]
        post_is_k     = {
            k: [[solver.Element(tbl_is_k[k], idx[e][d]) for d in range(D - TRAINING)] for e in range(E)]
            for k in range(1, S)
        }

        # ── TRAINING HOURS CONSTRAINTS ───────────────────────────────────
        # If shift==0 (off): hours=0. If working: hours in [minC, maxD].
        # is_off = 1 iff perm assigns off on day d.
        is_off_on_d = [
            [1 if perm_shift[p][d] == 0 else 0 for p in range(P)]
            for d in range(TRAINING)
        ]
        for e in range(E):
            for d in range(TRAINING):
                h      = train_hours[e][d]
                is_off = solver.Element(is_off_on_d[d], perm[e])
                solver.Add(h <= maxD * (1 - is_off))       # off  -> h = 0
                solver.Add(h >= minC  - maxD * is_off)     # work -> h >= minC

        # ── DEMAND CONSTRAINTS ───────────────────────────────────────────
        # Training days: fires immediately when perm[e] is assigned.
        for d in range(TRAINING):
            for k in range(1, S):
                solver.Add(
                    solver.Sum([
                        solver.Element(has_k_on_d[k][d], perm[e]) for e in range(E)
                    ]) >= self.minDemandDayShift[d][k]
                )

        # Post-training days
        for d in range(D - TRAINING):
            for k in range(1, S):
                solver.Add(
                    solver.Sum([post_is_k[k][e][d] for e in range(E)])
                    >= self.minDemandDayShift[TRAINING + d][k]
                )

        # ── WEEKLY HOURS ─────────────────────────────────────────────────
        for e in range(E):
            for w in range(W):
                week_days = range(w * 7, min((w + 1) * 7, D))
                wh = solver.Sum([
                    train_hours[e][d]          if d < TRAINING
                    else post_hours[e][d - TRAINING]
                    for d in week_days
                ])
                solver.Add(wh >= self.minWeeklyWork)
                solver.Add(wh <= self.maxWeeklyWork)

        # ── NIGHT SHIFT CONSTRAINTS ──────────────────────────────────────
        for e in range(E):
            all_is_night = (
                [train_is_night[e][d] for d in range(TRAINING)] +
                [post_is_night[e][d]  for d in range(D - TRAINING)]
            )

            # Total nights across horizon
            solver.Add(solver.Sum(all_is_night) <= self.maxTotalNightShift)

            # No two consecutive nights
            for d in range(D - self.maxConsecutiveNightShift):
                solver.Add(
                    solver.Sum(all_is_night[d : d + self.maxConsecutiveNightShift + 1])
                    <= self.maxConsecutiveNightShift
                )

        # ── DAILY OPERATION ──────────────────────────────────────────────
        for d in range(D):
            day_hours = solver.Sum([
                train_hours[e][d]          if d < TRAINING
                else post_hours[e][d - TRAINING]
                for e in range(E)
            ])
            solver.Add(day_hours >= self.minDailyOperation)

        # ── SYMMETRY BREAKING ────────────────────────────────────────────
        # Employees are symmetric w.r.t. permutation choice, so enforce
        # lexicographic order on perm values to eliminate duplicate solutions.
        # Unlike shift-based symmetry breaking, perm ordering does not interact
        # with AllDifferent (there is none here) and is safe to apply.
        for e in range(E - 1):
            solver.Add(perm[e] <= perm[e + 1])

        # ── SEARCH ───────────────────────────────────────────────────────
        # Phase 1: assign perm vars — immediately fires training demand on
        #          all 4 days simultaneously (vs. 3*E incremental assignments).
        # Phase 2: assign post-training idx vars column-major so per-day
        #          demand constraints propagate across all employees at once.
        # Phase 3: fill training hours (nearly determined after perm is fixed).
        post_idx_vars   = [idx[e][d] for d in range(D - TRAINING) for e in range(E)]
        train_hour_vars = [train_hours[e][d] for e in range(E) for d in range(TRAINING)]

        phase1 = solver.Phase(perm,           solver.CHOOSE_MIN_SIZE_LOWEST_MIN, solver.ASSIGN_MIN_VALUE)
        phase2 = solver.Phase(post_idx_vars,  solver.CHOOSE_MIN_SIZE_LOWEST_MIN, solver.ASSIGN_CENTER_VALUE)
        phase3 = solver.Phase(train_hour_vars,solver.CHOOSE_FIRST_UNBOUND,       solver.ASSIGN_MAX_VALUE)
        db     = solver.Compose([phase1, phase2, phase3])

        # ── MONITORS ─────────────────────────────────────────────────────
        # Luby restarts: geometrically growing failure budget
        #   1, 1, 2, 1, 1, 2, 4, 1, 1, 2, 1, 1, 2, 4, 8, ... (x scale)
        # scale=100 lets the solver explore enough local structure before
        # restarting, while preventing exhaustive descent into dead subtrees.
        monitors = [solver.LubyRestart(100)]
        if time_limit_seconds is not None:
            monitors.append(solver.TimeLimit(int(time_limit_seconds * 1000)))
        solver.NewSearch(db, monitors)

        if solver.NextSolution():
            sched = []
            for e in range(E):
                row = []
                p = perm[e].Value()
                for d in range(D):
                    if d < TRAINING:
                        k = perm_shift[p][d]
                        h = train_hours[e][d].Value()
                    else:
                        i = idx[e][d - TRAINING].Value()
                        k, h = tbl_shift[i], tbl_hours[i]
                    row.append((-1, -1) if k == 0 else (SHIFT_START[k], SHIFT_START[k] + h))
                sched.append(row)
            solver.EndSearch()
            return True, solver.Failures(), sched

        solver.EndSearch()
        return False, solver.Failures(), None
            

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
            if e < 9: print(" ", end="")
            for d in range(numDays):
                begin = sched[e][d][0]
                end = sched[e][d][1]
                for i in range(self.numIntervalsInDay):
                    if i % 8 == 0: print("|", end="")
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
