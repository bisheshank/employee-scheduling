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
        employee_shifts = [[self.solver.IntVar(0, 3)  for _ in range(self.numDays)] for _ in range(self.numEmployees)]

        # list of employee start times
        # employee_start_times = [[self.solver.IntVar(0, 20) for _ in range(self.numDays)] for _ in range(self.numEmployees)]

        # must work at least 4 consecutive hours per shift (minConsecutiveWork)
        # employees can't work more than 8 hours a day
        hours_per_shift = [0] + list(range(self.minConsecutiveWork, self.maxDailyWork + 1))

        # list of employee how many hours they work for that day
        employee_hours = [[self.solver.IntVar(hours_per_shift) for _ in range(self.numDays)] for _ in range(self.numEmployees)]

        ### CONSTRAINTS

        # employee can only work one shift a day

        for i in range(self.numDays):
            count1 = self.solver.IntVar(0, self.numDays)
            count2 = self.solver.IntVar(0, self.numDays)
            count3 = self.solver.IntVar(0, self.numDays)

            self.solver.Add(self.solver.Distribute(employee_shifts[i], [1, 2, 3], [count1, count2, count3]))

            # min employees needed every day for each shift (minDemandDayShift)
            self.solver.Add(count1 >= self.minDemandDayShift[i][0])
            self.solver.Add(count2 >= self.minDemandDayShift[i][1])
            self.solver.Add(count3 >= self.minDemandDayShift[i][2])

            # min # hours of work carried out a day (minDailyOperation)
            self.solver.Add(self.solver.Sum(employee_hours[i]) >= self.minDailyOperation)

            for j in range(self.numEmployees):            
                # total weekly hours must be btwn (minWeeklyWork, maxWeeklyWork) -> change to days (minWeeklyWork / 4, ...)
                if i % 7 == 0:
                    self.solver.Add(self.solver.Sum(employee_hours[i-7:i][j]).Between(self.minWeeklyWork, self.maxWeeklyWork))

                # night shifts cant follow each other (maxConsecutiveNightShift)
                if i != 0:
                    b = [self.solver.IsEqualCstVar(employee_shifts[i][j], 3) for d 
                    b2 = self.solver.IsEqualCstVar(employee_shifts[i][j], 3)
                    self.solver.Add(b1 + b2 <= 1)   # both can't be 1 (i.e. true) at the same time

        for j in range(self.numEmployees):
            # first 4 days => each employee assigned to unique shift
            self.solver.Add(self.solver.AllDifferent(employee_shifts[0:4][j]))

            # limit to total # of night shifts across scheduling horizon (maxTotalNightShift)
            count3 = self.solver.IntVar(0, self.numDays)

            self.solver.Add(self.solver.Count(employee_shifts[:][j], 3, count3))
            self.solver.Add(count3 <= self.maxTotalNightShift)



        # solve
        db = self.solver.DefaultPhase(...)
        self.solver.NewSearch(db)

        if self.solver.NextSolution():
            schedule = ...
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
