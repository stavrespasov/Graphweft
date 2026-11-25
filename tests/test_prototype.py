import json
from itertools import combinations, product
from pathlib import Path
import unittest

import numpy as np

from graphweft.audit import audit_plan
from graphweft.model import Model
from graphweft.transport import compare

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def example(name):
    return json.loads((EXAMPLES / name).read_text())


class TransportTests(unittest.TestCase):
    def test_two_node_chain(self):
        model = Model.from_dict(example("binary_chain.json"))
        result = compare(model)
        self.assertEqual(result["ordinary"]["cost"], 0.5)
        self.assertEqual(result["constrained"]["cost"], 1.0)
        self.assertEqual(result["cost_gap"], 0.5)
        self.assertTrue(result["constrained"]["audit"]["admissible"])
        self.assertFalse(result["ordinary"]["audit"]["admissible"])
        self.assertTrue(any(
            item["kind"] == "conditional_marginal" for item in result["ordinary"]["audit"]["failures"]
        ))

    def test_fork_with_effect_on_the_optimum(self):
        model = Model.from_dict(example("binary_fork.json"))
        result = compare(model)
        self.assertEqual(result["ordinary"]["cost"], 1)
        self.assertEqual(result["constrained"]["cost"], 1.5)
        self.assertTrue(result["constrained"]["audit"]["admissible"])

    def test_one_node_matches_classical(self):
        model = Model.from_dict({
            "nodes": ["A"], "parents": {"A": []},
            "source": [0.75, 0.25], "target": [0.25, 0.75],
        })
        result = compare(model)
        self.assertEqual(result["ordinary"]["cost"], result["constrained"]["cost"])
        self.assertEqual(result["constrained"]["cost"], 0.5)

    def test_edgeless_model_decomposes(self):
        model = Model.from_dict({
            "nodes": ["A", "B"], "parents": {"A": [], "B": []},
            "source": [0.375, 0.375, 0.125, 0.125],
            "target": [0.125, 0.125, 0.375, 0.375],
        })
        self.assertEqual(compare(model)["constrained"]["cost"], 0.5)

    def test_colliders_are_outside_solver_domain(self):
        case = example("shared_coin_model.json")
        case["parents"] = {"A": [], "B": [], "C": ["A", "B"]}
        model = Model.from_dict(case)
        with self.assertRaisesRegex(ValueError, "perfect DAG"):
            compare(model)
        self.assertTrue(audit_plan(model, np.diag(model.source))["admissible"])


class AuditTests(unittest.TestCase):
    def test_shared_coin_passes_ancestral_checks_but_fails_the_audit(self):
        model = Model.from_dict(example("shared_coin_model.json"))
        plan = np.array(example("shared_coin_plan.json"))
        bits = [tuple(map(int, state)) for state in model.states]

        # Independently implement the weaker ancestral tests in both directions.
        for directional in (plan, plan.T):
            for size in range(model.width + 1):
                for selection in combinations(range(model.width), size):
                    if any(not set(model.parents[i]).issubset(selection) for i in selection):
                        continue
                    observed = {}
                    for i, source in enumerate(bits):
                        context = tuple(source[j] for j in selection)
                        conditional = {
                            output: sum(
                                directional[i, k] for k, target in enumerate(bits)
                                if tuple(target[j] for j in selection) == output
                            ) / directional[i].sum()
                            for output in product((0, 1), repeat=size)
                        }
                        self.assertEqual(observed.setdefault(context, conditional), conditional)

        result = audit_plan(model, plan)
        self.assertFalse(result["admissible"])
        self.assertEqual({item["kind"] for item in result["failures"]}, {"history_dependence"})
        first = result["failures"][0]
        self.assertEqual(first["node"], "C")
        self.assertEqual(first["history"], {"A": [0, 0], "B": [0, 0]})
        self.assertEqual(first["observed"], [0.5, 0, 0, 0.5])
        self.assertEqual(first["required"], [0.25, 0.25, 0.25, 0.25])
        self.assertTrue(audit_plan(model, np.outer(model.source, model.target))["admissible"])

    def test_malformed_and_wrong_marginal_plans(self):
        model = Model.from_dict(example("binary_chain.json"))
        with self.assertRaisesRegex(ValueError, "shape"):
            audit_plan(model, [[1]])
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            audit_plan(model, np.full((4, 4), -1))
        result = audit_plan(model, np.zeros((4, 4)))
        self.assertFalse(result["admissible"])
        self.assertEqual([f["kind"] for f in result["failures"]], ["joint_marginal", "joint_marginal"])

    def test_invalid_graph_and_incompatible_joint_are_rejected(self):
        case = example("binary_chain.json")
        case["parents"] = {"A": ["B"], "B": []}
        with self.assertRaisesRegex(ValueError, "appearing before"):
            Model.from_dict(case)
        case["parents"] = {"A": [], "B": []}
        with self.assertRaisesRegex(ValueError, "incompatible"):
            Model.from_dict(case)
