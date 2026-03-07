# Employee Scheduling - CP Solver

A constraint programming solution for employee scheduling using Google OR-Tools CP Solver.

## Model Optimizations

### Hours-Only Variable Simplification

The original model used 4 decision variables per employee-day:
- `shift[e][d]` - which shift (off, night, day, evening)
- `begin[e][d]` - start hour
- `end[e][d]` - end hour
- `hours[e][d]` - hours worked

We simplified this to just 2 variables:
- `shift[e][d]` - which shift
- `hours[e][d]` - hours worked

The key insight is that no constraint in the problem actually depends on specific begin/end times. All constraints only care about:
- Which shift an employee is assigned to (for demand, training, night shift limits)
- How many hours they work (for weekly totals, daily operation)

The begin/end times are computed in post-processing based on shift and hours.

This reduces the search space by 50% (from 4 variables to 2 per employee-day) and shrinks the table constraint tuples from ~50+ combinations to just 16.

### Table Constraint Simplification

Before:
```python
valid_tuples = [(shift, begin, end, hours), ...]  # ~50+ tuples
AllowedAssignments([shift, begin, end, hours], valid_tuples)
```

After:
```python
valid_tuples = [(shift, hours), ...]  # 16 tuples
AllowedAssignments([shift, hours], valid_tuples)
```

The 16 tuples are:
- (OFF_SHIFT, 0) - off shift
- (1, 4), (1, 5), (1, 6), (1, 7), (1, 8) - night shift with 4-8 hours
- (2, 4), (2, 5), (2, 6), (2, 7), (2, 8) - day shift with 4-8 hours
- (3, 4), (3, 5), (3, 6), (3, 7), (3, 8) - evening shift with 4-8 hours

### Distribute Constraint for Demand

Replaced multiple Sum constraints for shift demand with a single Distribute (global cardinality) constraint per day:

Before:
```python
for s in WORKING_SHIFTS:
    solver.Add(Sum([shift[e][d] == s for e in range(E)]) >= demand[d][s])
```

After:
```python
solver.Add(solver.Distribute(day_shifts, values, card_min, card_max))
```

This uses specialized propagation that can be more efficient than individual counting constraints.

### BetweenCt for Weekly Hours

Replaced two separate min/max constraints with a single BetweenCt:

Before:
```python
solver.Add(Sum(week_hours) >= minWeeklyWork)
solver.Add(Sum(week_hours) <= maxWeeklyWork)
```

After:
```python
solver.Add(solver.BetweenCt(week_sum, minWeeklyWork, maxWeeklyWork))
```

## Post-Processing: Start Time Distribution

Instead of assigning all employees the same start time for their shift, we distribute start times across the valid range when multiple employees share the same shift on the same day.

This creates more realistic schedules where employees have staggered start times.

### How it works

1. Group employees by (day, shift)
2. Sort each group by hours worked (shorter shifts sorted first)
3. Evenly space start times across each employee's valid range

### Example

Before distribution (everyone starts at shift start):
```
Day Shift, 4 employees with varying hours:
  E1 (6 hrs): 8-14
  E2 (6 hrs): 8-14
  E3 (4 hrs): 8-12
  E4 (8 hrs): 8-16
```

After distribution:
```
Day Shift, sorted by hours, distributed starts:
  E3 (4 hrs): 8-12   (range [8,12], idx 0)
  E1 (6 hrs): 9-15   (range [8,10], idx 1)
  E2 (6 hrs): 10-16  (range [8,10], idx 2)
  E4 (8 hrs): 8-16   (range [8,8], no flexibility)
```

### Valid start ranges by shift

- Night (0-8): begin can be in [0, 8 - hours]
- Day (8-16): begin can be in [8, 16 - hours]
- Evening (16-24): begin can be in [16, 24 - hours]

## Usage

```bash
# Compile
./compile.sh

# Run single instance
./run.sh inputs/21_30.sched

# Run all instances with 60 second time limit
./runAll.sh inputs/ 60 results.log
```

## Validation

A validator is included to check solutions against all constraints:

```bash
cd src
python validator.py ../results.log --inputs-dir ../inputs
```

The validator checks:
- Valid shift/time assignments
- Min consecutive work (4 hours)
- Max daily work (8 hours)
- Min/max weekly work (20-40 hours)
- Min demand per day per shift
- Min daily operation
- Training requirement (unique shifts in first 4 days)
- Max consecutive night shifts
- Max total night shifts

## File Structure

```
src/
  cpinstance.py  - Main CP model and solver
  main.py        - Entry point
  validator.py   - Solution validator
inputs/
  *.sched        - Problem instances
```
