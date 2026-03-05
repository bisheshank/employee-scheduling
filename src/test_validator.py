"""
Unit tests for the validator - demonstrates that each constraint is properly checked.
Run with: python -m pytest src/test_validator.py -v
Or simply: python src/test_validator.py
"""

import tempfile
import os
from validator import validate_solution, get_shift_from_times, ValidationResult


def create_temp_instance(
    num_days=7,
    num_employees=3,
    num_weeks=1,
    min_demand=None,
    min_daily_operation=12,
    min_consecutive_work=4,
    max_daily_work=8,
    min_weekly_work=20,
    max_weekly_work=40,
    max_consecutive_night=1,
    max_total_night=2,
):
    """Create a temporary .sched file for testing"""

    if min_demand is None:
        # Default: 1 worker needed for each working shift each day
        # Format: [off, night, day, evening] per day
        min_demand = [0, 1, 1, 1] * num_days

    content = f"""Business_numWeeks: {num_weeks}
Business_numDays: {num_days}
Business_numEmployees: {num_employees}
Business_numShifts: 4
Business_numIntervalsInDay: 24
Business_minDemandDayShift: {" ".join(map(str, min_demand))}
Business_minDailyOperation: {min_daily_operation}
Employee_minConsecutiveWork: {min_consecutive_work}
Employee_maxDailyWork: {max_daily_work}
Employee_minWeeklyWork: {min_weekly_work}
Employee_maxWeeklyWork: {max_weekly_work}
Employee_maxConsecutiveNigthShift: {max_consecutive_night}
Employee_maxTotalNigthShift: {max_total_night}
"""

    fd, path = tempfile.mkstemp(suffix=".sched")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def solution_from_schedule(schedule):
    """Convert schedule to solution string"""
    parts = []
    for emp in schedule:
        for begin, end in emp:
            parts.extend([str(begin), str(end)])
    return " ".join(parts)


class TestShiftDetection:
    """Test that shifts are correctly identified from times"""

    def test_off_shift(self):
        assert get_shift_from_times(-1, -1) == 0

    def test_night_shift(self):
        assert get_shift_from_times(0, 4) == 1
        assert get_shift_from_times(0, 8) == 1
        assert get_shift_from_times(4, 8) == 1

    def test_day_shift(self):
        assert get_shift_from_times(8, 12) == 2
        assert get_shift_from_times(8, 16) == 2
        assert get_shift_from_times(12, 16) == 2

    def test_evening_shift(self):
        assert get_shift_from_times(16, 20) == 3
        assert get_shift_from_times(16, 24) == 3
        assert get_shift_from_times(20, 24) == 3

    def test_invalid_crossing_boundaries(self):
        assert get_shift_from_times(6, 10) == -1  # crosses night->day
        assert get_shift_from_times(14, 18) == -1  # crosses day->evening


class TestMinConsecutiveWork:
    """Test minConsecutiveWork constraint"""

    def test_valid_4_hour_shift(self):
        path = create_temp_instance(
            num_days=4,
            num_employees=1,
            min_consecutive_work=4,
            min_demand=[0, 0, 0, 0] * 4,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        # 4 hours each day (valid)
        schedule = [[(8, 12), (0, 4), (16, 20), (-1, -1)]]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        # Check no minConsecutiveWork errors
        consec_errors = [e for e in result.errors if "minConsecutiveWork" in e]
        assert len(consec_errors) == 0, f"Unexpected errors: {consec_errors}"

    def test_invalid_3_hour_shift(self):
        path = create_temp_instance(
            num_days=4,
            num_employees=1,
            min_consecutive_work=4,
            min_demand=[0, 0, 0, 0] * 4,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        # 3 hours (invalid - below min)
        schedule = [[(8, 11), (-1, -1), (-1, -1), (-1, -1)]]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        assert not result.is_valid
        consec_errors = [e for e in result.errors if "minConsecutiveWork" in e]
        assert len(consec_errors) > 0, "Should have minConsecutiveWork error"


class TestMaxDailyWork:
    """Test maxDailyWork constraint"""

    def test_valid_8_hour_shift(self):
        path = create_temp_instance(
            num_days=4,
            num_employees=1,
            max_daily_work=8,
            min_demand=[0, 0, 0, 0] * 4,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        schedule = [[(8, 16), (-1, -1), (-1, -1), (-1, -1)]]  # 8 hours
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        daily_errors = [e for e in result.errors if "maxDailyWork" in e]
        assert len(daily_errors) == 0

    def test_invalid_9_hour_shift(self):
        path = create_temp_instance(
            num_days=4,
            num_employees=1,
            max_daily_work=8,
            min_demand=[0, 0, 0, 0] * 4,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        # Note: This would actually be invalid because 8-17 crosses shift boundary
        # Let's use a valid time range that exceeds 8 hours: this is actually impossible
        # within a single shift since shifts are 8 hours max. The constraint is satisfied
        # by the shift structure itself.
        # However, we can test by setting maxDailyWork=6
        os.unlink(path)

        path = create_temp_instance(
            num_days=4,
            num_employees=1,
            max_daily_work=6,
            min_demand=[0, 0, 0, 0] * 4,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        schedule = [[(8, 16), (-1, -1), (-1, -1), (-1, -1)]]  # 8 hours > 6 max
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        assert not result.is_valid
        daily_errors = [e for e in result.errors if "maxDailyWork" in e]
        assert len(daily_errors) > 0


class TestWeeklyHours:
    """Test min/max weekly work constraints"""

    def test_below_min_weekly(self):
        # 7 days, need 20 hours/week, but only work 16
        path = create_temp_instance(
            num_days=7,
            num_employees=1,
            min_weekly_work=20,
            max_weekly_work=40,
            min_demand=[0, 0, 0, 0] * 7,
            min_daily_operation=0,
        )
        # Only 4 days * 4 hours = 16 hours (< 20 min)
        schedule = [[(8, 12), (0, 4), (16, 20), (-1, -1),
                     (8, 12), (-1, -1), (-1, -1)]]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        assert not result.is_valid
        weekly_errors = [e for e in result.errors if "minWeeklyWork" in e]
        assert len(weekly_errors) > 0

    def test_above_max_weekly(self):
        path = create_temp_instance(
            num_days=7,
            num_employees=1,
            min_weekly_work=20,
            max_weekly_work=40,
            min_demand=[0, 0, 0, 0] * 7,
            min_daily_operation=0,
        )
        # 7 days * 6 hours = 42 hours (> 40 max)
        schedule = [[(8, 14), (0, 6), (16, 22), (8, 14),
                     (0, 6), (16, 22), (8, 14)]]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        assert not result.is_valid
        weekly_errors = [e for e in result.errors if "maxWeeklyWork" in e]
        assert len(weekly_errors) > 0


class TestDemand:
    """Test min demand per shift constraints"""

    def test_unmet_demand(self):
        # Require 2 workers for day shift on day 0, but only have 1
        # Format: [off, night, day, evening] per day
        min_demand = [0, 0, 2, 0] + [0, 0, 0, 0] * \
            6  # day 0: need 2 day-shift workers
        path = create_temp_instance(
            num_days=7,
            num_employees=2,
            min_demand=min_demand,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        # Only 1 worker on day shift for day 0
        schedule = [
            [(8, 12), (-1, -1), (-1, -1), (-1, -1), (-1, -1), (-1, -1), (-1, -1)],
            [
                (0, 4),
                (-1, -1),
                (-1, -1),
                (-1, -1),
                (-1, -1),
                (-1, -1),
                (-1, -1),
            ],  # Night, not day
        ]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        assert not result.is_valid
        demand_errors = [e for e in result.errors if "demand" in e.lower()]
        assert len(demand_errors) > 0


class TestMinDailyOperation:
    """Test min daily operation (total hours per day)"""

    def test_below_min_daily_operation(self):
        path = create_temp_instance(
            num_days=7,
            num_employees=2,
            min_daily_operation=20,  # Need 20 hours/day
            min_demand=[0, 0, 0, 0] * 7,
            min_weekly_work=0,
        )
        # Only 8 hours total on day 0 (< 20)
        schedule = [
            [(8, 12), (-1, -1), (-1, -1), (-1, -1), (-1, -1), (-1, -1), (-1, -1)],
            [(16, 20), (-1, -1), (-1, -1), (-1, -1), (-1, -1), (-1, -1), (-1, -1)],
        ]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        assert not result.is_valid
        op_errors = [e for e in result.errors if "minDailyOperation" in e]
        assert len(op_errors) > 0


class TestTraining:
    """Test training requirement (unique shifts in first 4 days)"""

    def test_repeated_shift_in_training(self):
        path = create_temp_instance(
            num_days=7,
            num_employees=1,
            min_demand=[0, 0, 0, 0] * 7,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        # Day shift repeated on day 0 and day 1 (violation)
        schedule = [[(8, 12), (8, 12), (0, 4), (16, 20),
                     (-1, -1), (-1, -1), (-1, -1)]]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        assert not result.is_valid
        training_errors = [e for e in result.errors if "Training" in e]
        assert len(training_errors) > 0

    def test_valid_training(self):
        path = create_temp_instance(
            num_days=7,
            num_employees=1,
            min_demand=[0, 0, 0, 0] * 7,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        # All 4 different shifts in first 4 days
        schedule = [[(8, 12), (0, 4), (16, 20), (-1, -1),
                     (8, 12), (8, 12), (8, 12)]]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        training_errors = [e for e in result.errors if "Training" in e]
        assert len(training_errors) == 0


class TestNightShifts:
    """Test consecutive and total night shift constraints"""

    def test_consecutive_night_shifts(self):
        path = create_temp_instance(
            num_days=7,
            num_employees=1,
            max_consecutive_night=1,
            max_total_night=3,
            min_demand=[0, 0, 0, 0] * 7,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        # 2 consecutive night shifts (violation with max=1)
        schedule = [[(0, 4), (0, 4), (8, 12), (16, 20),
                     (-1, -1), (-1, -1), (-1, -1)]]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        assert not result.is_valid
        consec_errors = [e for e in result.errors if "Consecutive night" in e]
        assert len(consec_errors) > 0

    def test_total_night_shifts_exceeded(self):
        path = create_temp_instance(
            num_days=7,
            num_employees=1,
            max_consecutive_night=1,
            max_total_night=2,
            min_demand=[0, 0, 0, 0] * 7,
            min_daily_operation=0,
            min_weekly_work=0,
        )
        # 3 total night shifts (violation with max=2)
        schedule = [[(0, 4), (8, 12), (0, 4), (16, 20),
                     (0, 4), (-1, -1), (-1, -1)]]
        result = validate_solution(path, solution_from_schedule(schedule))
        os.unlink(path)

        assert not result.is_valid
        total_errors = [e for e in result.errors if "Total night" in e]
        assert len(total_errors) > 0


def run_all_tests():
    """Run all tests and report results"""
    import traceback

    test_classes = [
        TestShiftDetection,
        TestMinConsecutiveWork,
        TestMaxDailyWork,
        TestWeeklyHours,
        TestDemand,
        TestMinDailyOperation,
        TestTraining,
        TestNightShifts,
    ]

    passed = 0
    failed = 0

    for test_class in test_classes:
        print(f"\n{'=' * 50}")
        print(f"Running {test_class.__name__}")
        print("=" * 50)

        instance = test_class()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                method = getattr(instance, method_name)
                try:
                    method()
                    print(f"  PASS: {method_name}")
                    passed += 1
                except AssertionError as e:
                    print(f"  FAIL: {method_name}")
                    print(f"        {e}")
                    failed += 1
                except Exception as e:
                    print(f"  ERROR: {method_name}")
                    print(f"        {e}")
                    traceback.print_exc()
                    failed += 1

    print(f"\n{'=' * 50}")
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 50)

    return failed == 0


if __name__ == "__main__":
    import sys

    success = run_all_tests()
    sys.exit(0 if success else 1)
