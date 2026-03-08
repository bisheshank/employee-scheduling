# Employee Scheduling - CP Solver

A constraint programming solution for employee scheduling using Google OR-Tools CP Solver (not CP-SAT). This project generates weekly schedules for manufacturing employees while respecting labor rules, training requirements, and production demands.

## Problem Overview

The scheduling problem involves assigning employees to shifts (Night: 0-8, Day: 8-16, Evening: 16-24, or Off) over a multi-week horizon. Each schedule must satisfy:

- **Training**: First 4 days require each employee to experience all 4 shift types (including off)
- **Demand**: Minimum employees per shift per day (`minDemandDayShift[day][shift]`)
- **Daily Operation**: Total hours worked across all employees meets daily minimum
- **Work Limits**: 4-8 hours per shift, 20-40 hours per week
- **Night Shift Limits**: No consecutive night shifts, capped total night shifts per employee

## Development Journey

### Initial Approach: 4-Variable Model

The first implementation used 4 decision variables per employee-day:
- `shift[e][d]` - which shift (off, night, day, evening)
- `begin[e][d]` - start hour (0-24)
- `end[e][d]` - end hour (0-24)
- `hours[e][d]` - hours worked (0-8)

We pre-computed valid `(shift, begin, end, hours)` tuples (~50+ combinations) and used `AllowedAssignments` table constraints. This worked for smaller instances but struggled with larger ones (21+ days, 30+ employees) - the search space was too large.

### Building the Validator

To verify our solutions were actually correct, we built a standalone validator (`src/validator.py`). This checks all 9 constraint types from the handout. We weren't even sure if the validator itself was correct initially, so we had some unit tests for it (`src/test_validator.py`).

Having an independent validator proved invaluable - it caught several edge cases in our model and gave us confidence when experimenting with optimizations.

### Optimization Discoveries

Through experimentation, we discovered several techniques that significantly improved performance:

1. **Constraint Ordering**: The order constraints are added affects propagation. Adding demand constraints early helps prune infeasible branches faster.

2. **Redundant Constraints**: Adding implied constraints (like upper bounds on off-shifts per day derived from demand) strengthens propagation even though they're logically redundant.

3. **Restarts**: `LubyRestart(100)` helps escape bad branches in loose instances where the solver might explore unproductive regions of the search tree.

### Key Insight: Hours-Only Variables

After class discussion about exploiting problem structure, we realized that **no constraint actually depends on specific begin/end times** - they only care about:
- Which shift an employee is assigned to (for demand, training, night limits)
- How many hours they work (for weekly totals, daily operation)

This led to our simplified 2-variable model that reduced search space by 50%.

## Model Details

### Decision Variables

The final model uses just 2 variables per employee-day (see `cpinstance.py:162-169`):
- `shift[e][d]` - which shift (domain: Off, Night=1, Day=2, Evening=3)
- `hours[e][d]` - hours worked (domain: 0, 4, 5, 6, 7, 8)

This reduces search space by 50% compared to the original 4-variable model. Begin/end times are computed post-solution based on shift and hours.

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

## Constraint Flags

The model uses a flag-based system for incremental testing of constraints. All flags are module-level constants at the top of `cpinstance.py`. This lets you easily toggle constraints on/off to see which ones impact solver performance or cause infeasibility.

### Core Constraints

These are required by the problem spec:

| Flag | Description |
|------|-------------|
| `ENABLE_TABLE_CONSTRAINTS` | Links shift and hours via valid (shift, hours) pairs |
| `ENABLE_TRAINING` | AllDifferent for first 4 days (each employee experiences all shifts) |
| `ENABLE_DEMAND` | Distribute constraint for minDemandDayShift |
| `ENABLE_MIN_DAILY_OPERATION` | Sum of hours per day >= minDailyOperation |
| `ENABLE_WEEKLY_HOURS` | BetweenCt for min/max weekly hours |
| `ENABLE_NIGHT_CONSECUTIVE` | Sliding window for maxConsecutiveNightShift |
| `ENABLE_NIGHT_TOTAL` | Total night shift limit per employee |

### Redundant Constraints

These are technically implied by other constraints but can strengthen propagation:

| Flag | Description |
|------|-------------|
| `ENABLE_SYMMETRY_BREAKING` | Lexicographic ordering of employee schedules |
| `ENABLE_REDUNDANT_MAX_OFF` | Upper bound on off-shifts per day (derived from demand) |
| `ENABLE_TOTAL_HORIZON` | Global min/max hours over entire scheduling period |
| `ENABLE_IMPLIED_WORKING_DAYS` | Min/max working days per employee |

### Search Strategy Flags

| Flag | Description |
|------|-------------|
| `IS_DEFAULT` | Use DefaultPhase search (vs custom Phase) |
| `IS_TIGHT` | Deterministic fail-first search (vs randomized exploration) |
| `IS_RESTART` | Enable LubyRestart for search diversification |

### Ethical/Employee-Friendly Flags

These control whether the model favors employee welfare vs productivity:

| Flag | Description |
|------|-------------|
| `ETHICAL_OFF_FIRST` | When True, OFF_SHIFT=0 so off-shifts are tried first with ASSIGN_MIN_VALUE. Gives employees more rest days. When False, OFF_SHIFT=4 so working shifts are preferred. |
| `ENABLE_POST_PROCESS` | When True, start times are evenly distributed within shifts for better coverage. When False, everyone starts at shift start time. |

Note on search performance: `ETHICAL_OFF_FIRST = False` can be faster because working shifts are more constrained (they affect demand, hours, night limits). Trying them first triggers more propagation and prunes the tree earlier. Off shifts are "free" - they don't constrain much - so trying them first means less early pruning. It's a trade-off between search speed and employee-friendly schedules.

`ENABLE_POST_PROCESS` is purely cosmetic for the solver (happens after search) but produces more realistic schedules where employees have staggered start times instead of everyone clocking in at once.

### Example Usage

To test which redundant constraints actually help:

```python
# Disable all redundant constraints
ENABLE_SYMMETRY_BREAKING = False
ENABLE_REDUNDANT_MAX_OFF = False
ENABLE_TOTAL_HORIZON = False
ENABLE_IMPLIED_WORKING_DAYS = False
```

Then run and compare the `Result` (failure count) against the baseline.

To compare business-first vs employee-first scheduling:

```python
# Business-first (default)
ETHICAL_OFF_FIRST = False
ENABLE_POST_PROCESS = True

# Employee-first
ETHICAL_OFF_FIRST = True
ENABLE_POST_PROCESS = True
```
