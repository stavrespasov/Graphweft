"""Compare greedy and exhaustive selection on the parity construction's edge catalogs."""

from fractions import Fraction
from itertools import combinations
import json
from math import ceil, comb

from scipy.stats import binom

SIGNAL = Fraction(3, 4)
C_MISMATCH_COST = Fraction(1, 2)
PARITY_SAVINGS = (SIGNAL - C_MISMATCH_COST) / 2
DECOY_EDGE = "U->V"


def greedy(candidates, budget, savings, *, stop_at_plateau):
    selected = ()
    for _ in range(budget):
        edge = max(
            (edge for edge in candidates if edge not in selected),
            key=lambda edge: savings((*selected, edge)),
        )
        expanded = (*selected, edge)
        if stop_at_plateau and savings(expanded) == savings(selected):
            break
        selected = expanded
    return selected


def compare_searches(parent_count, decoy_weight=Fraction(0)):
    parity_edges = tuple(f"A{index}->C" for index in range(1, parent_count + 1))
    required = set(parity_edges)
    candidates = (*parity_edges, DECOY_EDGE) if decoy_weight else parity_edges

    def savings(selected):
        parity = PARITY_SAVINGS if required.issubset(selected) else Fraction(0)
        decoy = decoy_weight / 2 if DECOY_EDGE in selected else Fraction(0)
        return parity + decoy

    optimum = max(combinations(candidates, parent_count), key=savings)
    fixed = greedy(candidates, parent_count, savings, stop_at_plateau=False)
    improving = greedy(candidates, parent_count, savings, stop_at_plateau=True)
    nodes = parent_count + 2 + (3 if decoy_weight else 0)
    base_edges = parent_count + 1 + (2 if decoy_weight else 0)
    forward_candidates = comb(nodes, 2) - base_edges
    return {
        "nodes": nodes,
        "budget": parent_count,
        "decoy_weight": float(decoy_weight),
        "catalog": candidates,
        "optimum": {"edges": optimum, "savings": float(savings(optimum))},
        "fixed_budget_greedy": {"edges": fixed, "savings": float(savings(fixed))},
        "stop_at_plateau": {"edges": improving, "savings": float(savings(improving))},
        "greedy_fraction_of_optimal_savings": float(savings(fixed) / savings(optimum)),
        "full_forward_catalog_budget_subsets": comb(forward_candidates, parent_count),
        "dense_coupling_cells": 4 ** nodes,
    }


def estimation_sensitivity():
    strength, decoy_weight = Fraction(11, 20), Fraction(1, 32)
    rows = []
    for per_law in (64, 256, 1024):
        # A tie has equal savings, so count only fits strictly above the threshold.
        max_flips = ceil(per_law * (1 - C_MISMATCH_COST - decoy_weight)) - 1
        rows.append({
            "observations_per_law": per_law,
            "probability_fit_prefers_parity_edges": float(binom.cdf(
                max_flips, 2 * per_law, float((1 - strength) / 2),
            )),
        })
    return {
        "strength": float(strength),
        "decoy_weight": float(decoy_weight),
        "preference_threshold": float(C_MISMATCH_COST + decoy_weight),
        "results": rows,
    }


def main():
    print(json.dumps({
        "strength": float(SIGNAL),
        "plateau_examples": [compare_searches(parents) for parents in range(2, 7)],
        "strict_examples": [
            compare_searches(parents, weight)
            for parents in (2, 3) for weight in (Fraction(1, 16), Fraction(1, 64))
        ],
        "estimation_sensitivity": estimation_sensitivity(),
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
