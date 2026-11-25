import json
from pathlib import Path
import unittest

import numpy as np

from graphweft.edge_study import compare_added_edge, scan_added_edges
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

    def test_scan_ranks_independent_additions_and_preserves_witnesses(self):
        model = json.loads((EXAMPLES / "four_node_collider.json").read_text())
        scan = scan_added_edges(model)
        self.assertEqual(verify_run(scan["original"])["input"]["model"], model)
        self.assertEqual([study["edge"] for study in scan["edges"]], [["A", "C"], ["A", "B"]])
        self.assertEqual([study["cost_decrease"] for study in scan["edges"]], [0.25, 0])
        for study in scan["edges"]:
            parent, child = study["edge"]
            with self.subTest(parent=parent, child=child):
                separate = compare_added_edge(model, parent, child)
                self.assertEqual({"original": scan["original"], **study}, separate)
                expanded = verify_run(study["expanded"])["input"]["model"]
                expected = {**model["parents"], child: sorted([*model["parents"][child], parent])}
                self.assertEqual(expanded["parents"], expected)

    def test_scan_preserves_order_for_ties_and_returns_no_candidates_for_complete_graph(self):
        model = {
            "nodes": ["A", "B", "C"], "parents": {"A": [], "B": [], "C": []},
            "source": [0.125] * 8, "target": [0.125] * 8,
        }
        edges = scan_added_edges(model)["edges"]
        self.assertEqual([study["edge"] for study in edges], [["A", "B"], ["A", "C"], ["B", "C"]])
        self.assertTrue(all(study["cost_decrease"] == 0 for study in edges))
        model["parents"] = {"A": [], "B": ["A"], "C": ["A", "B"]}
        self.assertEqual(scan_added_edges(model)["edges"], [])

    def test_gain_within_solver_tolerance_reports_zero_decrease(self):
        model = json.loads((EXAMPLES / "four_node_collider.json").read_text())
        model["cost_factors"]["C"] = [[1 - 1e-9 if x % 2 != y % 2 else 0 for y in range(4)] for x in range(4)]
        study = compare_added_edge(model, "A", "C")
        before = study["original"]["result"]["constrained"]["cost"]
        after = study["expanded"]["result"]["constrained"]["cost"]
        self.assertLess(after, before)
        self.assertEqual(study["cost_decrease"], 0)
