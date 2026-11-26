"""Build the Capital Bikeshare study from the public UCI archive."""

import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import hashlib
from io import TextIOWrapper
from itertools import product
import json
from math import prod
from pathlib import Path
from statistics import median
from zipfile import ZipFile

from graphweft.edge_study import search_added_edges
from graphweft.experiments import create_run

ARCHIVE_SHA256 = "b70182d0d0508e9abbb79306ce5c0cec34869000f8220175ac83d11dbe845401"
HOURS = (8, 12, 18)
NODES = tuple(f"{hour:02d}:00" for hour in HOURS)
STATES = tuple(product((0, 1), repeat=len(HOURS)))
GROUPS = {1: "source", 0: "target"}


def read_days(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("The archive SHA-256 differs from the one recorded in the study.")
    counts = defaultdict(dict)
    working = {}
    with ZipFile(path) as archive, TextIOWrapper(archive.open("hour.csv"), encoding="utf-8") as hourly:
        for row in csv.DictReader(hourly):
            day = row["dteday"]
            working[day] = int(row["workingday"])
            hour = int(row["hr"])
            if hour in HOURS:
                counts[day][hour] = int(row["cnt"])
    observed = {day: tuple(counts[day][hour] for hour in HOURS) for day in working if len(counts[day]) == len(HOURS)}
    return observed, working


def day_counts(observed, working, thresholds):
    counts = {side: Counter() for side in GROUPS.values()}
    for day, rentals in observed.items():
        state = tuple(int(count >= threshold) for count, threshold in zip(rentals, thresholds))
        counts[GROUPS[working[day]]][state] += 1
    return counts


def chain_law(counts):
    root = [Fraction(sum(counts[state] for state in STATES if state[0] == bit), counts.total()) for bit in (0, 1)]
    transitions = []
    for node in range(1, len(NODES)):
        rows = []
        for parent in (0, 1):
            masses = [sum(counts[state] for state in STATES if state[node - 1 : node + 1] == (parent, bit))
                      for bit in (0, 1)]
            total = sum(masses)
            rows.append([Fraction(mass, total) if total else Fraction(1, 2) for mass in masses])
        transitions.append(rows)
    return [root[state[0]] * prod(table[parent][bit] for table, parent, bit in zip(transitions, state, state[1:]))
            for state in STATES]


def make_model(laws, full_history):
    return {
        "nodes": list(NODES),
        "parents": {
            node: list(NODES[:index] if full_history else NODES[max(0, index - 1) : index])
            for index, node in enumerate(NODES)
        },
        **{side: [float(mass) for mass in law] for side, law in laws.items()},
    }


def describe_costs(run):
    return {
        plan: {"cost": run["result"][plan]["cost"], "cost_by_hour": run["result"][plan]["cost_by_node"]}
        for plan in ("ordinary", "constrained")
    }


def write_json(path, document):
    path.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="UCI Bike Sharing Dataset zip file")
    parser.add_argument("output", type=Path, help="Directory for the two replayable reports")
    args = parser.parse_args()
    observed, working = read_days(args.archive)
    medians = [Fraction(median(rentals[column] for rentals in observed.values())) for column in range(len(HOURS))]
    summary = {
        "hours": list(NODES),
        "observed_days": len(working),
        "excluded_dates": sorted(working.keys() - observed.keys()),
        "threshold_sweep": [],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for multiplier in (Fraction(1), Fraction(9, 10), Fraction(11, 10)):
        thresholds = [cutoff * multiplier for cutoff in medians]
        counts = day_counts(observed, working, thresholds)
        empirical = {side: [Fraction(group[state], group.total()) for state in STATES] for side, group in counts.items()}
        chain = {side: chain_law(group) for side, group in counts.items()}
        chain_model = make_model(chain, full_history=False)
        full = create_run({"operation": "compare", "model": make_model(empirical, full_history=True)})
        if multiplier == 1:
            search = search_added_edges(chain_model)
            base = search["original"]
            write_json(args.output / "chain-search.json", search)
            write_json(args.output / "full-history-run.json", full)
            summary["observed_state_counts"] = {side: [group[state] for state in STATES] for side, group in counts.items()}
            summary["chain_fit_total_variation"] = {
                side: float(sum(abs(actual - fitted) for actual, fitted in zip(empirical[side], chain[side])) / 2)
                for side in counts
            }
            summary["fixed_law_shortcut_cost"] = search["best_additions"][0]["expanded"]["result"]["constrained"]["cost"]
        else:
            base = create_run({"operation": "compare", "model": chain_model})
        summary["threshold_sweep"].append({
            "multiplier": float(multiplier),
            "thresholds": [float(cutoff) for cutoff in thresholds],
            "chain_fit": describe_costs(base),
            "full_history_fit": describe_costs(full),
        })
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
