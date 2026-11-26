"""Rebuild the household appliance-energy comparison from the UCI archive."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, time
from fractions import Fraction
import hashlib
from io import TextIOWrapper
from itertools import product
import json
from pathlib import Path
from statistics import median
from zipfile import ZipFile

from graphweft.experiments import create_run

ARCHIVE_SHA256 = "2fccf354445d886e7917620b0195db1f3e3e34d5a067a93b844694a4c561255a"
HOURS = (time(8), time(12), time(18))
NODES = tuple(hour.isoformat(timespec="minutes") for hour in HOURS)
STATES = tuple(product((0, 1), repeat=len(HOURS)))


def read_days(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("The archive SHA-256 differs from the one recorded in the study.")
    readings = defaultdict(dict)
    with ZipFile(path) as archive, TextIOWrapper(archive.open("energydata_complete.csv"), encoding="utf-8") as rows:
        for row in csv.DictReader(rows):
            timestamp = datetime.fromisoformat(row["date"])
            day = readings[timestamp.date()]
            hour = timestamp.time()
            if hour in HOURS:
                if hour in day:
                    raise ValueError(f"Duplicate measurement at {timestamp}.")
                day[hour] = int(row["Appliances"])
    observed = {
        date: tuple(values[hour] for hour in HOURS)
        for date, values in readings.items() if len(values) == len(HOURS)
    }
    return observed, sorted(readings.keys() - observed.keys())


def make_model(observed, thresholds):
    groups = {"source": Counter(), "target": Counter()}
    for date, readings in observed.items():
        side = "source" if date.weekday() < 5 else "target"
        groups[side][tuple(int(value >= cutoff) for value, cutoff in zip(readings, thresholds))] += 1
    counts = {side: [group[state] for state in STATES] for side, group in groups.items()}
    if not all(map(sum, counts.values())):
        raise ValueError("The comparison needs at least one complete weekday and weekend day.")
    model = {
        "nodes": list(NODES),
        "parents": {node: list(NODES[:index]) for index, node in enumerate(NODES)},
        **{side: [count / sum(masses) for count in masses] for side, masses in counts.items()},
    }
    return model, counts


def rebuild(archive, output):
    observed, excluded = read_days(archive)
    medians = [Fraction(median(values)) for values in zip(*observed.values())]
    summary = {
        "observed_days": len(observed) + len(excluded),
        "excluded_dates": [date.isoformat() for date in excluded],
        "threshold_sweep": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    for multiplier in (Fraction(1), Fraction(9, 10), Fraction(11, 10)):
        thresholds = [cutoff * multiplier for cutoff in medians]
        model, counts = make_model(observed, thresholds)
        run = create_run({"operation": "compare", "model": model})
        result = run["result"]
        if multiplier == 1:
            summary["observed_state_counts"] = counts
            (output / "full-history-run.json").write_text(
                json.dumps(run, indent=2, allow_nan=False) + "\n", encoding="utf-8",
            )
        summary["threshold_sweep"].append({
            "multiplier": float(multiplier),
            "thresholds_wh": [float(cutoff) for cutoff in thresholds],
            "costs": {name: result[name]["cost"] for name in ("ordinary", "constrained")},
            "cost_gap": result["cost_gap"],
        })
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="UCI Appliances Energy Prediction zip file")
    parser.add_argument("output", type=Path, help="Directory for the replayable report")
    args = parser.parse_args()
    print(json.dumps(rebuild(args.archive, args.output), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
