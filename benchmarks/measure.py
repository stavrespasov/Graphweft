"""Measure GraphWeft's supported problem sizes with seeded full-support laws."""

import argparse
from itertools import product
import json
from math import prod
import platform
from random import Random
from statistics import median
from time import perf_counter
import tracemalloc

import networkx
import numpy

from graphweft.edge_study import search_added_edges
from graphweft.model import Model
from graphweft.transport import compare


def specification(parents, seed):
    nodes = tuple(parents)
    states = tuple(product((0, 1), repeat=len(nodes)))
    axes = [tuple(nodes.index(parent) for parent in parents[node]) for node in nodes]
    rng = Random(seed)
    laws = {}
    for side in ("source", "target"):
        probabilities = [
            {context: rng.choice((0.25, 0.5, 0.75)) for context in product((0, 1), repeat=len(past))}
            for past in axes
        ]
        law = []
        for state in states:
            rates = (row[tuple(state[j] for j in past)] for row, past in zip(probabilities, axes))
            law.append(prod(rate if bit else 1 - rate for bit, rate in zip(state, rates)))
        laws[side] = law
    return {"nodes": list(nodes), "parents": parents, **laws}


def profile(operation, samples):
    operation()
    elapsed = []
    for _ in range(samples):
        start = perf_counter()
        operation()
        elapsed.append((perf_counter() - start) * 1000)

    tracemalloc.start()
    try:
        result = operation()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "wall_ms": {"min": min(elapsed), "median": median(elapsed), "max": max(elapsed)},
        "peak_traced_kib": peak / 1024,
        "graphs_evaluated": result.get("graphs_evaluated", 1),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=9, help="Timed repetitions per workload")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")

    chain = {"A": [], "B": ["A"], "C": ["B"], "D": ["C"]}
    workloads = [
        (f"chain-{width}", dict(list(chain.items())[:width]), compare) for width in range(1, 5)
    ]
    workloads.extend((
        ("complete-4", {node: list(chain)[:index] for index, node in enumerate(chain)}, compare),
        ("collider-3", {"A": [], "B": [], "C": ["A", "B"]}, compare),
        ("internal-collider-4", {"A": [], "B": [], "C": ["A", "B"], "D": ["A", "C"]}, compare),
        ("edge-search-4", {node: [] for node in chain}, search_added_edges),
    ))

    seed = 358
    rows = []
    for name, parents, solve in workloads:
        raw = specification(parents, seed)
        data = Model.from_dict(raw) if solve is compare else raw
        rows.append({
            "case": name,
            "binary_nodes": len(parents),
            "coupling_cells": 4 ** len(parents),
            **profile(lambda: solve(data), args.samples),
        })
    print(json.dumps({
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": numpy.__version__,
            "networkx": networkx.__version__,
        },
        "seed": seed,
        "timed_samples": args.samples,
        "results": rows,
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
