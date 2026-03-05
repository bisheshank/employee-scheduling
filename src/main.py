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
        default=300,
        help="Time limit in seconds (default: none)",
    )
    args = parser.parse_args()

    input_file = Path(args.input_file)
    filename = input_file.name

    instance = CPInstance(str(input_file))
    timer = Timer()
    timer.start()
    is_solution, n_fails, schedule = instance.solve(time_limit_seconds=args.time_limit)
    timer.stop()

    resultdict = {}
    resultdict["Instance"] = filename
    resultdict["Time"] = timer.getTime()
    resultdict["Result"] = str(n_fails)
    resultdict["Solution"] = schedule 
    # feel free to return a different format for schedule from instance.solve
    # but make sure the Solution matches the format in the handout!

    # Pretty prints solution, uncomment to use
    # if is_solution:
    #     instance.prettyPrint(instance.numEmployees, instance.numDays, schedule)
    #     instance.generateVisualizerInput(instance.numEmployees, instance.numDays, schedule)
    print(json.dumps(resultdict))

if __name__ == "__main__":
    main()
