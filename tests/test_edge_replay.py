from copy import deepcopy
import json
from pathlib import Path
import unittest

from graphweft.audit import audit_plan
from graphweft.edge_study import EDGE_SEARCH_SCHEMA, compare_added_edge, search_added_edges, verify_edge_search
from graphweft.experiments import verify_saved_document
from graphweft.model import Model

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class EdgeReplayTests(unittest.TestCase):
    def setUp(self):
        self.specification = json.loads((EXAMPLES / "interacting_edges.json").read_text())
        self.report = search_added_edges(self.specification)

    def test_round_trip_verifies_the_complete_search(self):
        verified = verify_saved_document(json.loads(json.dumps(self.report)))
        self.assertEqual(verified["schema"], EDGE_SEARCH_SCHEMA)
        self.assertEqual(verified, self.report)

    def test_replay_accepts_a_different_tied_combination(self):
        alternative = compare_added_edge(self.specification, "A", "C")
        self.assertNotEqual(self.report["best_additions"][0]["added_edges"], [["A", "C"]])
        del alternative["original"]
        alternative["added_edges"] = [alternative.pop("edge")]
        self.report["best_additions"][0] = alternative
        self.assertEqual(verify_edge_search(self.report)["best_additions"][0], alternative)

    def test_replay_rejects_a_valid_run_from_a_suboptimal_combination(self):
        first = compare_added_edge(self.specification, "A", "B")["expanded"]
        second = compare_added_edge(first["input"]["model"], "A", "C")["expanded"]
        model = Model.from_dict(self.specification)
        self.report["best_additions"][1] = {
            "added_edges": [["A", "B"], ["A", "C"]],
            "expanded": second,
            "cost_decrease": 0,
            "original_graph_audit": audit_plan(model, second["result"]["constrained"]["plan"]),
        }
        with self.assertRaisesRegex(ValueError, "does not attain the best cost"):
            verify_edge_search(self.report)

    def test_replay_rejects_a_valid_run_with_changed_costs(self):
        changed = {**self.specification, "cost_factors": {"C": [[0, 0.75], [0.75, 0]]}}
        self.report["best_additions"][0]["expanded"] = compare_added_edge(changed, "A", "B")["expanded"]
        with self.assertRaisesRegex(ValueError, "preserve the original laws and costs"):
            verify_edge_search(self.report)

    def test_replay_rejects_false_counts_edges_cost_decreases_and_audits(self):
        changes = [
            ((), "graphs_evaluated", 7, "graphs evaluated"),
            ((), "minimum_edges_to_ordinary", 1, "minimum edges to ordinary"),
            (("best_additions", 1), "added_edges", [["A", "C"], ["A", "C"]], "distinct missing forward edges"),
            (("best_additions", 1), "cost_decrease", 0, "cost decrease"),
            (("best_additions", 1, "original_graph_audit"), "admissible", True, "original-graph audit"),
        ]
        for path, key, value, error in changes:
            with self.subTest(path=path, key=key):
                altered = deepcopy(self.report)
                target = altered
                for part in path:
                    target = target[part]
                target[key] = value
                with self.assertRaisesRegex(ValueError, error):
                    verify_edge_search(altered)

    def test_replay_verifies_a_complete_graph_with_a_remaining_gap(self):
        specification = json.loads((EXAMPLES / "binary_chain.json").read_text())
        report = search_added_edges(specification)
        self.assertEqual(report["graphs_evaluated"], 1)
        self.assertIsNone(report["minimum_edges_to_ordinary"])
        self.assertEqual(verify_edge_search(report), report)
