from itertools import product
import json
from pathlib import Path
import unittest

from graphweft.audit import audit_plan
from graphweft.experiments import create_run, verify_run
from graphweft.model import Model
from graphweft.transport import compare

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def fixture(filename):
    return json.loads((EXAMPLES / filename).read_text())


class ColliderTests(unittest.TestCase):
    def test_adding_the_root_edge_changes_the_constrained_optimum(self):
        collider_input = fixture("binary_collider.json")
        ordered_input = fixture("ordered_control.json")
        self.assertEqual(
            {**collider_input, "parents": ordered_input["parents"]},
            ordered_input,
        )
        collider = Model.from_dict(collider_input)
        ordered = Model.from_dict(ordered_input)
        result = compare(collider)
        control = compare(ordered)
        self.assertEqual(result["ordinary"]["cost"], 0.5)
        self.assertEqual(control["ordinary"]["cost"], 0.5)
        self.assertEqual(result["constrained"]["cost"], 1.0)
        self.assertEqual(control["constrained"]["cost"], 0.5)
        self.assertEqual(result["constrained"]["cost_by_node"], {"A": 0, "B": 0, "C": 1.0})
        self.assertEqual(control["constrained"]["cost_by_node"], {"A": 0, "B": 0.5, "C": 0})
        self.assertTrue(result["constrained"]["audit"]["admissible"])
        self.assertTrue(control["constrained"]["audit"]["admissible"])

        audit = audit_plan(collider, control["constrained"]["plan"])
        self.assertFalse(audit["admissible"])
        first = audit["failures"][0]
        self.assertEqual((first["kind"], first["node"]), ("history_dependence", "B"))
        self.assertEqual(first["parents"], {})
        self.assertEqual(first["history"], {"A": [0, 0]})
        self.assertEqual(first["required"], [0.25] * 4)

    def test_full_permutation_enumeration_for_uniform_binary_kernels(self):
        root_a = [[2, 0], [1, 3]]
        root_b = [[0, 3], [2, 1]]
        child = [[((13 * x + 7 * y + 3 * x * y) % 17) / 4 for y in range(8)] for x in range(8)]
        case = fixture("binary_collider.json")
        case["source"] = [0.125] * 8
        case["target"] = [0.125] * 8
        case["cost_factors"] = {"A": root_a, "B": root_b, "C": child}
        model = Model.from_dict(case)

        # For fair binary inputs, each extreme kernel is a bit flip or identity.
        # Enumerate both root maps and all child maps for the four reachable root pairs.
        objectives = []
        for flip_a, flip_b, *child_flips in product((0, 1), repeat=6):
            total = 0
            for x, (a, b, c) in enumerate(product((0, 1), repeat=3)):
                y_a, y_b, y_c = a ^ flip_a, b ^ flip_b, c ^ child_flips[2 * a + b]
                y = 4 * y_a + 2 * y_b + y_c
                total += root_a[a][y_a] + root_b[b][y_b] + child[x][y]
            objectives.append(total / 8)

        result = compare(model)["constrained"]
        self.assertAlmostEqual(result["cost"], min(objectives))
        self.assertTrue(result["audit"]["admissible"])

    def test_collider_run_can_be_saved_and_verified(self):
        saved = create_run({"operation": "compare", "model": fixture("binary_collider.json")})
        verified = verify_run(json.loads(json.dumps(saved)))
        self.assertEqual(verified["result"], saved["result"])
