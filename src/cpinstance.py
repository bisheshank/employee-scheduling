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
    
        solver = self.solver
        E  = self.numEmployees
        D  = self.numDays
        W  = self.numWeeks
        S  = self.numShifts

        SHIFT_START = [0, 0, 8, 16]
        SHIFT_END   = [0, 8, 16, 24]
        minC = self.minConsecutiveWork
        maxD = self.maxDailyWork
        TRAINING = min(4, D)

        # ── PRECOMPUTE IDX TABLE ─────────────────────────────────────────
        table = [(0, 0)]
        for k in range(1, S):
            window = SHIFT_END[k] - SHIFT_START[k]
            for h in range(minC, min(maxD, window) + 1):
                table.append((k, h))

        N         = len(table)
        tbl_shift = [row[0] for row in table]
        tbl_hours = [row[1] for row in table]
        tbl_is_night = [1 if row[0] == 1 else 0 for row in table]
        tbl_is_k = {
            k: [1 if row[0] == k else 0 for row in table]
            for k in range(1, S)
        }

        # ── PRECOMPUTE ALL 4! TRAINING PERMUTATIONS ──────────────────────
        # Each permutation is a list of 4 shift values [s0, s1, s2, s3]
        # where each of {0,1,2,3} appears exactly once.
        from itertools import permutations
        all_perms = list(permutations(range(S)))  # 24 permutations
        P = len(all_perms)
        # perm_shift[p][d] = shift value for permutation p on training day d
        perm_shift = [[all_perms[p][d] for d in range(TRAINING)] for p in range(P)]

        # ── VARIABLES ────────────────────────────────────────────────────
        # Training: one permutation index per employee (0..23)
        perm = [solver.IntVar(0, P - 1, f"perm_{e}") for e in range(E)]

        # Post-training days: one idx per (employee, day)
        idx = [
            [solver.IntVar(0, N - 1, f"idx_{e}_{d}") for d in range(TRAINING, D)]
            for e in range(E)
        ]

        # Training shift for each (employee, training_day) derived from perm via Element
        # perm_shift[p][d] for employee e on day d = Element(perm_shift_col[d], perm[e])
        train_shift = [
            [solver.Element([perm_shift[p][d] for p in range(P)], perm[e])
            for d in range(TRAINING)]
            for e in range(E)
        ]

        # Derived expressions for post-training days
        post_shift    = [[solver.Element(tbl_shift,    idx[e][d - TRAINING]) for d in range(TRAINING, D)] for e in range(E)]
        post_hours    = [[solver.Element(tbl_hours,    idx[e][d - TRAINING]) for d in range(TRAINING, D)] for e in range(E)]
        post_is_night = [[solver.Element(tbl_is_night, idx[e][d - TRAINING]) for d in range(TRAINING, D)] for e in range(E)]
        post_is_k = {
            k: [[solver.Element(tbl_is_k[k], idx[e][d - TRAINING]) for d in range(TRAINING, D)] for e in range(E)]
            for k in range(1, S)
        }

        # Unified accessors across all days
        def get_shift(e, d):
            return train_shift[e][d] if d < TRAINING else post_shift[e][d - TRAINING]

        def get_hours(e, d):
            # Training hours: if off (shift==0) hours=0, else need a variable
            # Use Element over a per-perm hours table — but hours aren't fixed by perm.
            # Use a separate hours var for training days.
            return train_hours[e][d] if d < TRAINING else post_hours[e][d - TRAINING]

        def get_is_night(e, d):
            if d < TRAINING:
                # shift==1 iff perm assigns night on day d
                night_by_perm = [1 if perm_shift[p][d] == 1 else 0 for p in range(P)]
                return solver.Element(night_by_perm, perm[e])
            return post_is_night[e][d - TRAINING]

        # Training hours variables (shift is fixed by perm, hours still free within shift)
        train_hours = [
            [solver.IntVar(0, maxD, f"th_{e}_{d}") for d in range(TRAINING)]
            for e in range(E)
        ]

        # ── TRAINING HOURS CONSTRAINTS ───────────────────────────────────
        for e in range(E):
            for d in range(TRAINING):
                h  = train_hours[e][d]
                ts = train_shift[e][d]
                # is_off_train = 1 iff shift == 0
                is_off_t = solver.IsEqualCstVar(ts, 0)
                solver.Add(h <= maxD * (1 - is_off_t))
                solver.Add(h >= minC - maxD * is_off_t)
                solver.Add(h <= maxD)

        # ── DEMAND ON TRAINING DAYS (fires immediately after perm assigned) ──
        for d in range(TRAINING):
            for k in range(1, S):
                # count of employees whose perm assigns shift k on day d
                has_k_on_d = [1 if perm_shift[p][d] == k else 0 for p in range(P)]
                solver.Add(
                    solver.Sum([solver.Element(has_k_on_d, perm[e]) for e in range(E)])
                    >= self.minDemandDayShift[d][k]
                )

        # ── POST-TRAINING DEMAND ─────────────────────────────────────────
        for d in range(TRAINING, D):
            for k in range(1, S):
                solver.Add(
                    solver.Sum([post_is_k[k][e][d - TRAINING] for e in range(E)])
                    >= self.minDemandDayShift[d][k]
                )

        # ── WEEKLY HOURS ─────────────────────────────────────────────────
        for e in range(E):
            for w in range(W):
                week_days = range(w * 7, min((w + 1) * 7, D))
                wh = solver.Sum([
                    train_hours[e][d] if d < TRAINING else post_hours[e][d - TRAINING]
                    for d in week_days
                ])
                solver.Add(wh >= self.minWeeklyWork)
                solver.Add(wh <= self.maxWeeklyWork)

        # ── NIGHT SHIFT CONSTRAINTS ──────────────────────────────────────
        for e in range(E):
            all_is_night = [get_is_night(e, d) for d in range(D)]

            # Total nights
            solver.Add(solver.Sum(all_is_night) <= self.maxTotalNightShift)

            # No consecutive nights
            for d in range(D - self.maxConsecutiveNightShift):
                solver.Add(
                    solver.Sum(all_is_night[d:d + self.maxConsecutiveNightShift + 1])
                    <= self.maxConsecutiveNightShift
                )

        # ── DAILY OPERATION ──────────────────────────────────────────────
        for d in range(D):
            day_hours = solver.Sum([
                train_hours[e][d] if d < TRAINING else post_hours[e][d - TRAINING]
                for e in range(E)
            ])
            solver.Add(day_hours >= self.minDailyOperation)

        # ── SYMMETRY BREAKING ────────────────────────────────────────────
        for e in range(E - 1):
            solver.Add(perm[e] <= perm[e + 1])

        # ── SEARCH ───────────────────────────────────────────────────────
        # Phase 1: assign training permutations — immediately fires demand
        #          on all 4 training days simultaneously
        # Phase 2: assign post-training idx vars
        # Phase 3: assign training hours (nearly free once shifts known)
        post_idx_vars   = [idx[e][d] for d in range(D - TRAINING) for e in range(E)]
        train_hour_vars = [train_hours[e][d] for e in range(E) for d in range(TRAINING)]

        phase1 = solver.Phase(perm, solver.CHOOSE_MIN_SIZE_LOWEST_MIN, solver.ASSIGN_MIN_VALUE)
        phase2 = solver.Phase(post_idx_vars, solver.CHOOSE_MIN_SIZE_LOWEST_MIN, solver.ASSIGN_CENTER_VALUE)
        phase3 = solver.Phase(train_hour_vars, solver.CHOOSE_FIRST_UNBOUND, solver.ASSIGN_MAX_VALUE)
        db = solver.Compose([phase1, phase2, phase3])

        monitors = []
        if time_limit_seconds is not None:
            monitors.append(solver.TimeLimit(int(time_limit_seconds * 1000)))
        solver.NewSearch(db, monitors)

        if solver.NextSolution():
            sched = []
            for e in range(E):
                row = []
                p = perm[e].Value()  # integer 0..23 — the chosen permutation
                for d in range(D):
                    if d < TRAINING:
                        k = perm_shift[p][d]              # read shift from table, not from expr
                        h = train_hours[e][d].Value()     # plain IntVar, has .Value()
                    else:
                        i = idx[e][d - TRAINING].Value()  # plain IntVar, has .Value()
                        k, h = tbl_shift[i], tbl_hours[i]
                    if k == 0:
                        row.append((-1, -1))
                    else:
                        row.append((SHIFT_START[k], SHIFT_START[k] + h))
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
