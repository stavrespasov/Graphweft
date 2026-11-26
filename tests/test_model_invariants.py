from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import unittest

import numpy as np

from graphweft.audit import audit_plan
from graphweft.model import Model
from graphweft.transport import compare

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _weighted_collider():
    model = json.loads((EXAMPLES / "four_node_collider.json").read_text())
    model["cost_factors"]["D"] = [[(3 * x * y + 11 * x + 5 * y) % 17 for y in range(16)] for x in range(16)]
    return model


def _indices_in_order(before, after):
    return [int("".join(state[after.index(name)] for name in before), 2)
            for state in product("01", repeat=len(after))]


class ModelInvariantTests(unittest.TestCase):
    def test_valid_topological_reordering_preserves_both_optima(self):
        original = _weighted_collider()
        reordered = deepcopy(original)
        reordered["nodes"] = ["B", "A", "C", "D"]
        state_order = _indices_in_order(original["nodes"], reordered["nodes"])
        for side in ("source", "target"):
            reordered[side] = [original[side][index] for index in state_order]
        for node, table in original["cost_factors"].items():
            parents = original["parents"][node]
            old_family = [name for name in original["nodes"] if name in parents] + [node]
            new_family = [name for name in reordered["nodes"] if name in parents] + [node]
            order = _indices_in_order(old_family, new_family)
            reordered["cost_factors"][node] = [[table[i][j] for j in order] for i in order]

        before = compare(Model.from_dict(original))
        new_model = Model.from_dict(reordered)
        after = compare(new_model)
        for solver in ("ordinary", "constrained"):
            self.assertAlmostEqual(before[solver]["cost"], after[solver]["cost"])
        relabeled_plan = np.asarray(before["constrained"]["plan"])[np.ix_(state_order, state_order)]
        self.assertTrue(audit_plan(new_model, relabeled_plan)["admissible"])

    def test_transposing_laws_costs_and_witness_preserves_the_optima(self):
        model = _weighted_collider()
        reversed_model = Model.from_dict({
            **model, "source": model["target"], "target": model["source"],
            "cost_factors": {node: np.asarray(table).T.tolist() for node, table in model["cost_factors"].items()},
        })
        before = compare(Model.from_dict(model))
        after = compare(reversed_model)
        for solver in ("ordinary", "constrained"):
            self.assertAlmostEqual(before[solver]["cost"], after[solver]["cost"])
        self.assertTrue(audit_plan(reversed_model, np.asarray(before["constrained"]["plan"]).T)["admissible"])

    def test_model_rejects_invalid_shape_graph_and_probability_values(self):
        model = {"nodes": ["A"], "parents": {"A": []}, "source": [1, 0], "target": [1, 0]}
        for key, value, message in (
            ("nodes", list("ABCDE"), "one to four"), ("nodes", ["A", "A"], "distinct"),
            ("parents", {"A": ["A"]}, "appearing before"), ("parents", {"B": []}, "every node"),
            ("source", [0.25, 0.25], "sum to one"), ("source", [1, -1e-12], "nonnegative"),
            ("source", [True, 0], "numeric array"), ("source", ["1", 0], "numeric array"),
            ("source", [float("nan"), 0], "finite"), ("source", [float("inf"), 0], "finite"),
            ("cost_factors", {"A": [[0, True], [1, 0]]}, "numeric array"),
        ):
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(ValueError, message):
                    Model.from_dict({**model, key: value})
        with self.assertRaisesRegex(ValueError, "numeric array"):
            audit_plan(Model.from_dict(model), [[True, 0], [0, 0]])
