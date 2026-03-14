"""
Employee Scheduling Solution Validator

Validates all constraints from the handout:
1. Valid shift/time assignments
2. Min consecutive work
3. Max daily work
4. Min/Max weekly work
5. Min demand per day per shift
6. Min daily operation
7. Training requirement (unique shifts in first 4 days)
8. Max consecutive night shifts
9. Max total night shifts
"""

import json
import sys
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Holds results of validation"""

    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add_error(self, msg: str):
        self.is_valid = False
        self.errors.append(msg)

    def add_warning(self, msg: str):
        self.warnings.append(msg)


def get_shift_from_times(begin: int, end: int) -> int:
    """
    Determine shift from begin/end times.
    Returns: 0=Off, 1=Night, 2=Day, 3=Evening
    """
    if begin == -1 and end == -1:
        return 0  # Off shift

    # Night: [0, 8), Day: [8, 16), Evening: [16, 24)
    if 0 <= begin < 8 and 0 < end <= 8:
        return 1  # Night
    elif 8 <= begin < 16 and 8 < end <= 16:
        return 2  # Day
    elif 16 <= begin < 24 and 16 < end <= 24:
        return 3  # Evening
    else:
        return -1  # Invalid


def parse_instance(filename: str) -> dict:
    """Parse the .sched instance file"""
    params = {}
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                if key == "Business_minDemandDayShift":
                    params[key] = [int(x) for x in value.split()]
                else:
                    try:
                        params[key] = int(value)
                    except ValueError:
                        params[key] = value
    return params


def parse_solution(
    solution_str: str, num_employees: int, num_days: int
) -> List[List[Tuple[int, int]]]:
    """
    Parse solution string into schedule.
    Returns: schedule[employee][day] = (begin, end)
    """
    values = [int(x) for x in solution_str.split()]
    expected = num_employees * num_days * 2

    if len(values) != expected:
        raise ValueError(f"Expected {expected} values, got {len(values)}")

    schedule = []
    idx = 0
    for e in range(num_employees):
        employee_schedule = []
        for d in range(num_days):
            begin = values[idx]
            end = values[idx + 1]
            employee_schedule.append((begin, end))
            idx += 2
        schedule.append(employee_schedule)

    return schedule


def validate_solution(
    instance_file: str, solution_str: str, verbose: bool = True
) -> ValidationResult:
    """
    Validate a solution against all constraints.
    """
    result = ValidationResult()

    # Parse instance
    params = parse_instance(instance_file)

    num_weeks = params.get("Business_numWeeks", 1)
    num_days = params.get("Business_numDays")
    num_employees = params.get("Business_numEmployees")
    num_shifts = params.get("Business_numShifts", 4)

    min_demand_raw = params.get("Business_minDemandDayShift", [])
    min_daily_operation = params.get("Business_minDailyOperation", 0)

    min_consecutive_work = params.get("Employee_minConsecutiveWork", 4)
    max_daily_work = params.get("Employee_maxDailyWork", 8)
    min_weekly_work = params.get("Employee_minWeeklyWork", 20)
    max_weekly_work = params.get("Employee_maxWeeklyWork", 40)
    max_consecutive_night = params.get("Employee_maxConsecutiveNigthShift", 1)
    max_total_night = params.get("Employee_maxTotalNigthShift", 2)

    # Parse minDemandDayShift into [day][shift] format
    # Format: day0_off, day0_night, day0_day, day0_evening, day1_off, ...
    # Array indexed [0]=off, [1]=night, [2]=day, [3]=evening
    min_demand = []
    if min_demand_raw:
        for d in range(num_days):
            start_idx = d * num_shifts
            # Skip off (index 0), take night/day/evening (indices 1,2,3)
            day_demand = min_demand_raw[start_idx + 1: start_idx + 4]
            min_demand.append(day_demand)

    # Parse solution
    try:
        schedule = parse_solution(solution_str, num_employees, num_days)
    except ValueError as e:
        result.add_error(f"Failed to parse solution: {e}")
        return result

    # Statistics
    total_hours = 0
    shift_counts = {0: 0, 1: 0, 2: 0, 3: 0}  # off, night, day, evening

    # ===== VALIDATION =====

    # 1. Validate each employee's schedule
    for e in range(num_employees):
        employee_night_count = 0
        consecutive_night = 0
        max_consec_night_seen = 0

        for d in range(num_days):
            begin, end = schedule[e][d]

            # Check for off shift
            if begin == -1 and end == -1:
                shift = 0
                hours = 0
                consecutive_night = 0
            else:
                # Validate begin/end are reasonable
                if begin < 0 or begin > 24 or end < 0 or end > 24:
                    result.add_error(
                        f"E{e + 1} D{d + 1}: Invalid times ({begin}, {end})"
                    )
                    continue

                if end <= begin:
                    result.add_error(
                        f"E{e + 1} D{d + 1}: End ({end}) must be > begin ({begin})")
                    continue

                hours = end - begin
                shift = get_shift_from_times(begin, end)

                if shift == -1:
                    result.add_error(
                        f"E{e + 1} D{d + 1}: Times ({begin}, {end}) don't fit any valid shift")
                    continue

                # 2. Min consecutive work
                if hours < min_consecutive_work:
                    result.add_error(
                        f"E{e + 1} D{d + 1}: Hours worked ({hours}) < minConsecutiveWork ({min_consecutive_work})")

                # 3. Max daily work
                if hours > max_daily_work:
                    result.add_error(
                        f"E{e + 1} D{d + 1}: Hours worked ({hours}) > maxDailyWork ({max_daily_work})")

                total_hours += hours

                # Track night shifts
                if shift == 1:
                    employee_night_count += 1
                    consecutive_night += 1
                    max_consec_night_seen = max(
                        max_consec_night_seen, consecutive_night
                    )
                else:
                    consecutive_night = 0

            shift_counts[shift] += 1

        # 8. Max consecutive night shifts
        if max_consec_night_seen > max_consecutive_night:
            result.add_error(
                f"E{e + 1}: Consecutive night shifts ({max_consec_night_seen}) > maxConsecutiveNightShift ({max_consecutive_night})")

        # 9. Max total night shifts
        if employee_night_count > max_total_night:
            result.add_error(
                f"E{e + 1}: Total night shifts ({employee_night_count}) > maxTotalNightShift ({max_total_night})")

    # 4. Weekly hours constraints
    for e in range(num_employees):
        for w in range(num_weeks):
            week_start = w * 7
            week_end = min(week_start + 7, num_days)

            if week_end - week_start < 7:
                # Incomplete week, skip validation
                continue

            week_hours = 0
            for d in range(week_start, week_end):
                begin, end = schedule[e][d]
                if begin != -1:
                    week_hours += end - begin

            if week_hours < min_weekly_work:
                result.add_error(
                    f"E{e + 1} Week{w + 1}: Hours ({week_hours}) < minWeeklyWork ({min_weekly_work})")
            if week_hours > max_weekly_work:
                result.add_error(
                    f"E{e + 1} Week{w + 1}: Hours ({week_hours}) > maxWeeklyWork ({max_weekly_work})")

    # 5. Min demand per day per shift
    for d in range(num_days):
        shift_workers = {1: 0, 2: 0, 3: 0}  # night, day, evening

        for e in range(num_employees):
            begin, end = schedule[e][d]
            shift = get_shift_from_times(begin, end)
            if shift in shift_workers:
                shift_workers[shift] += 1

        if min_demand and d < len(min_demand):
            for s_idx, demand in enumerate(min_demand[d]):
                shift_id = s_idx + 1  # 1=night, 2=day, 3=evening
                if demand > 0 and shift_workers.get(shift_id, 0) < demand:
                    result.add_error(
                        f"D{d + 1} Shift{shift_id}: Workers ({shift_workers.get(shift_id, 0)}) < demand ({demand})")

    # 6. Min daily operation
    for d in range(num_days):
        day_hours = 0
        for e in range(num_employees):
            begin, end = schedule[e][d]
            if begin != -1:
                day_hours += end - begin

        if day_hours < min_daily_operation:
            result.add_error(
                f"D{d + 1}: Total hours ({day_hours}) < minDailyOperation ({min_daily_operation})")

    # 7. Training requirement: unique shifts in first 4 days
    training_days = min(num_days, 4)
    if training_days == 4:
        for e in range(num_employees):
            training_shifts = set()
            for d in range(training_days):
                begin, end = schedule[e][d]
                shift = get_shift_from_times(begin, end)
                if shift in training_shifts:
                    result.add_error(
                        f"E{e + 1}: Training violation - shift {shift} repeated in first 4 days"
                    )
                training_shifts.add(shift)

            # Should have all 4 shifts (0, 1, 2, 3) in first 4 days
            expected_shifts = {0, 1, 2, 3}
            if training_shifts != expected_shifts:
                missing = expected_shifts - training_shifts
                result.add_warning(
                    f"E{e + 1}: Training - missing shifts {missing} in first 4 days"
                )

    # Collect statistics
    result.stats = {
        "total_hours": total_hours,
        "shift_counts": shift_counts,
        "num_employees": num_employees,
        "num_days": num_days,
        "avg_hours_per_employee_per_day": total_hours / (num_employees * num_days)
        if num_employees * num_days > 0
        else 0,
    }

    return result


def validate_results_log(results_file: str, inputs_dir: str, verbose: bool = True):
    """
    Validate all solutions in a results.log file.
    """
    results = []

    with open(results_file, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"Line {line_num}: Failed to parse JSON - {e}")
                continue

            instance_name = data.get("Instance")
            solution = data.get("Solution", "")
            result_val = data.get("Result")

            if result_val == "--" or not solution:
                print(f"\n{'=' * 60}")
                print(f"Instance: {instance_name}")
                print(f"Status: NO SOLUTION (Result: {result_val})")
                results.append((instance_name, None, "No solution"))
                continue

            instance_file = Path(inputs_dir) / instance_name

            if not instance_file.exists():
                print(f"\n{'=' * 60}")
                print(f"Instance: {instance_name}")
                print(f"Status: INPUT FILE NOT FOUND")
                results.append((instance_name, None, "Input not found"))
                continue

            validation = validate_solution(
                str(instance_file), solution, verbose)

            print(f"\n{'=' * 60}")
            print(f"Instance: {instance_name}")
            print(f"Time: {data.get('Time')}s, Failures: {result_val}")

            if validation.is_valid:
                print(f"Status: VALID")
            else:
                print(f"Status: INVALID ({len(validation.errors)} errors)")

            if validation.errors and verbose:
                print(f"\nErrors:")
                for err in validation.errors[:10]:  # Limit to first 10
                    print(f"  - {err}")
                if len(validation.errors) > 10:
                    print(f"  ... and {
                          len(validation.errors) - 10} more errors")

            if validation.warnings and verbose:
                print(f"\nWarnings:")
                for warn in validation.warnings[:5]:
                    print(f"  - {warn}")

            if verbose:
                print(f"\nStatistics:")
                print(f"  Total hours worked: {
                      validation.stats.get('total_hours', 0)}")
                print(
                    f"  Avg hours/employee/day: {validation.stats.get('avg_hours_per_employee_per_day', 0):.2f}")
                print(f"  Shift distribution: {validation.stats.get('shift_counts', {})}"
                      )

            results.append((instance_name, validation.is_valid, validation))

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)

    valid_count = sum(1 for _, is_valid, _ in results if is_valid is True)
    invalid_count = sum(1 for _, is_valid, _ in results if is_valid is False)
    no_solution = sum(1 for _, is_valid, _ in results if is_valid is None)

    print(f"Valid:       {valid_count}")
    print(f"Invalid:     {invalid_count}")
    print(f"No Solution: {no_solution}")
    print(f"Total:       {len(results)}")

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate employee scheduling solutions"
    )
    parser.add_argument("results_file", help="Path to results.log")
    parser.add_argument(
        "--inputs-dir", default="inputs", help="Directory containing .sched files"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress detailed output"
    )

    args = parser.parse_args()

    validate_results_log(args.results_file, args.inputs_dir,
                         verbose=not args.quiet)


if __name__ == "__main__":
    main()
