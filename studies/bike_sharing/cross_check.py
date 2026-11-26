"""Compare GraphWeft costs with the upstream AOTNumerics LP on the same inputs."""

import argparse
from itertools import product
import json
from math import isclose
from pathlib import Path
import subprocess
import sys

import numpy as np

from graphweft.model import Model
from graphweft.transport import compare

CHAIN_FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "binary_chain.json"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def hamming(left, right):
    return float(np.count_nonzero(left != right))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path, help="AOTNumerics checkout")
    parser.add_argument("reports", type=Path, help="Directory containing the bike-sharing reports")
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    commit = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    sys.path.insert(0, str(upstream))
    import gurobipy
    import ot
    from src.mainfunctions import gurobi_bm
    from src.normal_ot import solve_pot

    search = read_json(args.reports / "chain-search.json")
    refitted = read_json(args.reports / "full-history-run.json")
    cases = {
        "two_node_chain": read_json(CHAIN_FIXTURE),
        "bike_chain": search["original"]["input"]["model"],
        "bike_shortcut_fixed_laws": search["best_additions"][0]["expanded"]["input"]["model"],
        "bike_full_history_refit": refitted["input"]["model"],
    }
    results = {}
    for name, specification in cases.items():
        states = np.asarray(list(product((0, 1), repeat=len(specification["nodes"]))))
        measures = [(states, np.asarray(specification[side])) for side in ("source", "target")]
        reference = {
            "ordinary": float(solve_pot(measures, hamming, outputflag=0)),
            "constrained": float(gurobi_bm(measures, hamming, causal=1, anticausal=1, outputflag=0)),
        }
        run = compare(Model.from_dict(specification))
        measured = {plan: run[plan]["cost"] for plan in reference}
        if any(not isclose(measured[plan], value, rel_tol=0, abs_tol=1e-9) for plan, value in reference.items()):
            raise RuntimeError(f"The transport costs disagree for {name} ({measured} vs {reference}).")
        results[name] = {"graphweft": measured, "aotnumerics": reference}
    print(json.dumps({
        "aotnumerics_commit": commit,
        "gurobi": ".".join(map(str, gurobipy.gurobi.version())),
        "pot": ot.__version__,
        "cases": results,
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
