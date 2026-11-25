import json
from pathlib import Path
import unittest

import numpy as np

from graphweft.edge_study import compare_added_edge
from graphweft.experiments import verify_run
from graphweft.model import Model
from graphweft.transport import cost_matrices

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class EdgeStudyTests(unittest.TestCase):
    def test_collider_study_returns_two_verifiable_runs_and_cross_audit(self):
        model = json.loads((EXAMPLES / "binary_collider.json").read_text())
        study = compare_added_edge(model, "A", "B")
        original = verify_run(study["original"])
        expanded = verify_run(study["expanded"])
        self.assertEqual(original["input"]["model"], model)
        ordered = json.loads((EXAMPLES / "ordered_control.json").read_text())
        self.assertEqual(expanded["input"]["model"], ordered)
        self.assertEqual(original["result"]["ordinary"]["cost"], 0.5)
        self.assertEqual(expanded["result"]["ordinary"]["cost"], 0.5)
        self.assertEqual(original["result"]["constrained"]["cost"], 1.0)
        self.assertEqual(expanded["result"]["constrained"]["cost"], 0.5)
        self.assertEqual(study["cost_decrease"], 0.5)
        self.assertFalse(study["original_graph_audit"]["admissible"])
        failure = study["original_graph_audit"]["failures"][0]
        self.assertEqual((failure["kind"], failure["node"], failure["history"]),
                         ("history_dependence", "B", {"A": [0, 0]}))

    def test_adding_a_parent_preserves_asymmetric_costs_for_every_pair(self):
        for old_parent, added_parent in (("A", "B"), ("B", "A")):
            with self.subTest(added_parent=added_parent):
                model = {
                    "nodes": ["A", "B", "C"],
                    "parents": {"A": [], "B": [], "C": [old_parent]},
                    "source": [0.125] * 8,
                    "target": [0.125] * 8,
                    "cost_factors": {"C": np.arange(16).reshape(4, 4).tolist()},
                }
                original_input = json.loads(json.dumps(model))
                study = compare_added_edge(model, added_parent, "C")
                expanded = study["expanded"]["input"]["model"]
                self.assertEqual(model, original_input)
                self.assertEqual(expanded["parents"]["C"], ["A", "B"])
                self.assertEqual(expanded["source"], model["source"])
                self.assertEqual(expanded["target"], model["target"])
                np.testing.assert_array_equal(cost_matrices(Model.from_dict(expanded)),
                                              cost_matrices(Model.from_dict(model)))
                self.assertEqual(study["cost_decrease"], 0)

    def test_only_missing_edges_in_node_order_are_accepted(self):
        model = json.loads((EXAMPLES / "binary_collider.json").read_text())
        for parent, child, message in (
            ("X", "A", "node names"), ("B", "B", "appear before"),
            ("B", "A", "appear before"), ("A", "C", "already contains"),
        ):
            with self.subTest(parent=parent, child=child):
                with self.assertRaisesRegex(ValueError, message):
                    compare_added_edge(model, parent, child)
