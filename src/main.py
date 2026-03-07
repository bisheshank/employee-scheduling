import json
from argparse import ArgumentParser
from pathlib import Path
from cpinstance import CPInstance
from model_timer import Timer


def main():
    parser = ArgumentParser()
    parser.add_argument("input_file", type=str)
    parser.add_argument(
        "--time-limit",
        type=float,
        default=20,  # 30 seconds for now
        help="Time limit in seconds (default: None)",
    )
    args = parser.parse_args()

    input_file = Path(args.input_file)
    filename = input_file.name

    instance = CPInstance(str(input_file))
    timer = Timer()
    timer.start()
    is_solution, n_fails, schedule = instance.solve(
        time_limit_seconds=args.time_limit)
    timer.stop()

    resultdict = {}
    resultdict["Instance"] = filename
    resultdict["Time"] = round(timer.getTime(), 2)
    resultdict["Result"] = n_fails

    if is_solution:
        # 1. Flatten the schedule into a space-separated string for the JSON output
        solution_parts = []
        for e in range(instance.numEmployees):
            for d in range(instance.numDays):
                solution_parts.append(str(schedule[e][d][0]))
                solution_parts.append(str(schedule[e][d][1]))
        resultdict["Solution"] = " ".join(solution_parts)

        # 2. Pretty prints solution, uncomment to use
        # (These still work perfectly because 'schedule' is still the nested list!)
        # instance.prettyPrint(instance.numEmployees, instance.numDays, schedule)
        # instance.generateVisualizerInput(instance.numEmployees, instance.numDays, schedule)
    else:
        resultdict["Solution"] = ""

    # Print the final JSON exactly on one line
    print(json.dumps(resultdict))


if __name__ == "__main__":
    main()
