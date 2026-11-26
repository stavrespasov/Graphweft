"""Compare graph and sample-size effects in a controlled four-node model."""

import argparse
from itertools import product
import json
from pathlib import Path

import numpy as np

from graphweft.edge_study import search_added_edges
from graphweft.model import Model
from graphweft.transport import compare

NODES = ("A", "B", "C", "D")
STATES = tuple(product((0, 1), repeat=len(NODES)))
STRENGTHS = (0.0, 0.25, 0.5, 0.75, 1.0)
C_MISMATCH_COST = 0.5
GRAPHS = {
    "collider": (),
    "a_to_c": (("A", "C"),),
    "b_to_c": (("B", "C"),),
    "both_into_c": (("A", "C"), ("B", "C")),
    "complete": (("A", "B"), ("A", "C"), ("B", "C")),
}


def specification(strength, graph):
    parents = {"A": [], "B": [], "C": [], "D": ["A", "B", "C"]}
    for parent, child in GRAPHS[graph]:
        parents[child].append(parent)
    size = 2 ** (len(parents["C"]) + 1)
    return {
        "nodes": list(NODES),
        "parents": parents,
        "source": [(1 + strength if d == (a ^ b ^ c) else 1 - strength) / 16 for a, b, c, d in STATES],
        "target": [(1 + strength if d == c else 1 - strength) / 16 for a, b, c, d in STATES],
        "cost_factors": {"C": [
            [C_MISMATCH_COST if i % 2 != j % 2 else 0 for j in range(size)] for i in range(size)
        ]},
    }


def graph_sweep():
    rows = []
    for strength in STRENGTHS:
        costs = {}
        for graph in GRAPHS:
            result = compare(Model.from_dict(specification(strength, graph)))
            costs[graph] = {
                "ordinary": result["ordinary"]["cost"],
                "constrained": result["constrained"]["cost"],
                "gap": result["cost_gap"],
            }
        rows.append({"strength": strength, "costs": costs})
    return rows


def sample_size_sweep():
    strength, seed, replicates = 0.55, 82027, 2000
    rng = np.random.default_rng(seed)
    estimates = []
    for per_law in (64, 256, 1024):
        flips = rng.binomial(2 * per_law, (1 - strength) / 2, size=replicates)
        fitted_strength = np.maximum(0, 1 - flips / per_law)
        # The closed-form decrease is (s - 0.5) / 2 when s exceeds 0.5.
        gain = np.maximum(0, (fitted_strength - C_MISMATCH_COST) / 2)
        estimates.append({
            "observations_per_law": per_law,
            "fraction_with_positive_decrease": float(np.mean(gain > 0)),
            "cost_decrease_quantiles": dict(zip(
                ("p05", "median", "p95"), np.quantile(gain, (0.05, 0.5, 0.95)).tolist(),
            )),
        })
    return {
        "strength": strength,
        "seed": seed,
        "replicates": replicates,
        "numpy_version": np.__version__,
        "results": estimates,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write a replayable edge search at strength 0.75")
    args = parser.parse_args()
    if args.report is not None:
        report = search_added_edges(specification(0.75, "collider"))
        args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "graph_sweep": graph_sweep(),
        "sample_size_sweep": sample_size_sweep(),
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
