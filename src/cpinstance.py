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
    
        # TODO: your model goes here

        ### VARIABLES

        # list of employees shifts they take that day
        employee_shifts = [[self.solver.IntVar(0, 3) for _ in range(self.numEmployees)] for _ in range(self.numDays)]

        # list of employee start times
        # employee_start_times = [[self.solver.IntVar(0, 20) for _ in range(self.numDays)] for _ in range(self.numEmployees)]

        # must work at least 4 consecutive hours per shift (minConsecutiveWork)
        # employees can't work more than 8 hours a day [0, 4, 5, 6, 7, 8]
        hours_per_shift = [0] + list(range(self.minConsecutiveWork, self.maxDailyWork + 1))

        # list of employee how many hours they work for that day
        employee_hours = [[self.solver.IntVar(hours_per_shift) for _ in range(self.numEmployees)] for _ in range(self.numDays)] 

        ### CONSTRAINTS

        # employee can only work one shift a day

        for i in range(self.numDays):
            count1 = self.solver.IntVar(0, self.numDays)
            count2 = self.solver.IntVar(0, self.numDays)
            count3 = self.solver.IntVar(0, self.numDays)

            self.solver.Add(self.solver.Distribute(employee_shifts[i], [1, 2, 3], [count1, count2, count3]))

            # min employees needed every day for each shift (minDemandDayShift)
            self.solver.Add(count1 >= self.minDemandDayShift[i][1])
            self.solver.Add(count2 >= self.minDemandDayShift[i][2])
            self.solver.Add(count3 >= self.minDemandDayShift[i][3])

            # min # hours of work carried out a day (minDailyOperation)
            self.solver.Add(self.solver.Sum(employee_hours[i]) >= self.minDailyOperation)

            for j in range(self.numEmployees):
                # total weekly hours must be btwn (minWeeklyWork, maxWeeklyWork)
                # if i % 7 == 0 and i >= 7:
                #     weekly_sum = self.solver.Sum([employee_hours[d][j] for d in range(i-7, i)])
                #     self.solver.Add(weekly_sum >= self.minWeeklyWork)
                #     self.solver.Add(weekly_sum <= self.maxWeeklyWork)

                is_zero_shift = self.solver.IsEqualCstVar(employee_shifts[i][j], 0)
                is_zero_hours = self.solver.IsEqualCstVar(employee_hours[i][j], 0)

                self.solver.Add(self.solver.Max(employee_shifts[i][j], 0) * employee_hours[i][j] >= employee_shifts[i][j] * self.minConsecutiveWork)

                self.solver.Add(is_zero_shift == is_zero_hours)

        for j in range(self.numEmployees):
            # first 4 days => each employee assigned to unique shift
            self.solver.Add(self.solver.AllDifferent([employee_shifts[i][j] for i in range(min(self.numDays, 4))]))

            # limit to total # of night shifts across scheduling horizon (maxTotalNightShift)
            count3 = self.solver.IntVar(0, self.numDays)

            self.solver.Add(self.solver.Count([employee_shifts[i][j] for i in range(self.numDays)], 3, count3))
            self.solver.Add(count3 <= self.maxTotalNightShift)

            # total weekly hours must be btwn (minWeeklyWork, maxWeeklyWork)
            for week in range(self.numWeeks):
                start = week * 7
                end = start + 7
                if end <= self.numDays:
                    weekly_sum = self.solver.Sum([employee_hours[d][j] for d in range(start, end)])
                    self.solver.Add(weekly_sum >= self.minWeeklyWork)
                    self.solver.Add(weekly_sum <= self.maxWeeklyWork)

            # night shifts cant follow each other (maxConsecutiveNightShift)
            for i in range(self.numDays - self.maxConsecutiveNightShift):
                night_shift_bools = [
                    self.solver.IsEqualCstVar(employee_shifts[i + k][j], 1)
                    for k in range(self.maxConsecutiveNightShift + 1)
                ]
                self.solver.Add(self.solver.Sum(night_shift_bools) <= self.maxConsecutiveNightShift)



        # solve
        all_vars = (
            [employee_shifts[d][e] for d in range(self.numDays) for e in range(self.numEmployees)] +
            [employee_hours[d][e] for d in range(self.numDays) for e in range(self.numEmployees)]
        )
        db = self.solver.DefaultPhase(all_vars)
        self.solver.NewSearch(db)

        if self.solver.NextSolution():
            start_times = [-1, 0, 8, 16]
            schedule = [[[-1, -1] for _ in range(self.numDays)] for _ in range(self.numEmployees)]

            for d in range(self.numDays):
                for e in range(self.numEmployees):
                    if employee_shifts[d][e].Value() == 0:
                        continue
                    
                    schedule[e][d][0] = start_times[employee_shifts[d][e].Value()]
                    schedule[e][d][1] = schedule[e][d][0] + employee_hours[d][e].Value()

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
