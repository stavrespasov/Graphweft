import copy
import json
import math
from pathlib import Path
import unittest

from graphweft.model import Model
from graphweft.transport import compare

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def weighted_fork():
    return json.loads((EXAMPLES / "parent_weighted_fork.json").read_text())


class CostTests(unittest.TestCase):
    def test_parent_weighted_fork_and_contributions(self):
        model = Model.from_dict(weighted_fork())
        result = compare(model)
        self.assertEqual(result["ordinary"]["cost"], 1)
        self.assertEqual(result["constrained"]["cost"], 2.5)
        self.assertEqual(result["ordinary"]["cost_by_node"], {"A": 0.5, "B": 0.5, "C": 0})
        self.assertEqual(result["constrained"]["cost_by_node"], {"A": 0.5, "B": 0.5, "C": 1.5})
        self.assertEqual(result["cost_gap"], 1.5)
        self.assertTrue(result["constrained"]["audit"]["admissible"])

    def test_family_rows_and_columns_follow_model_order(self):
        # Point masses leave a single coupling. The C table reads all three bits.
        table = [[0] * 8 for _ in range(8)]
        table[5][2] = 7
        model = Model.from_dict({
            "nodes": ["A", "B", "C"],
            "parents": {"A": [], "B": ["A"], "C": ["B", "A"]},
            "source": [0, 0, 0, 0, 0, 1, 0, 0],
            "target": [0, 0, 1, 0, 0, 0, 0, 0],
            "cost_factors": {"C": table},
        })
        result = compare(model)
        for name in ("ordinary", "constrained"):
            self.assertAlmostEqual(result[name]["cost"], 9)
            self.assertAlmostEqual(result[name]["cost_by_node"]["C"], 7)
            self.assertEqual(result[name]["plan"][5][2], 1)

    def test_scaling_and_zero_objectives(self):
        for scale in (1e-200, 1e100):
            with self.subTest(scale=scale):
                case = weighted_fork()
                case["cost_factors"]["A"] = [[0, scale], [scale, 0]]
                case["cost_factors"]["B"] = [
                    [scale if row % 2 != col % 2 else 0 for col in range(4)]
                    for row in range(4)
                ]
                case["cost_factors"]["C"] = [
                    [value * scale for value in row] for row in case["cost_factors"]["C"]
                ]
                result = compare(Model.from_dict(case))
                self.assertAlmostEqual(result["ordinary"]["cost"] / scale, 1)
                self.assertAlmostEqual(result["constrained"]["cost"] / scale, 2.5)

        case = weighted_fork()
        case["cost_factors"] = {
            "A": [[0] * 2 for _ in range(2)],
            "B": [[0] * 4 for _ in range(4)],
            "C": [[0] * 4 for _ in range(4)],
        }
        result = compare(Model.from_dict(case))
        self.assertEqual(result["ordinary"]["cost"], 0)
        self.assertEqual(result["constrained"]["cost"], 0)
        self.assertTrue(result["constrained"]["audit"]["admissible"])

    def test_malformed_cost_factors_are_rejected(self):
        valid = weighted_fork()
        for factors, error in (
            ({"missing": [[0, 1], [1, 0]]}, "node names"),
            ({"C": [[0, 1], [1, 0]]}, "shape"),
            ({"A": [[0, -1], [1, 0]]}, "nonnegative"),
            ({"A": [[0, math.inf], [1, 0]]}, "finite"),
            ({"B": [[math.nan] * 4 for _ in range(4)]}, "finite"),
            ({
                "A": [[0, 1e308], [0, 0]],
                "B": [[1e308] * 4 for _ in range(4)],
            }, "maximum local costs"),
        ):
            with self.subTest(error=error, factors=factors):
                case = copy.deepcopy(valid)
                case["cost_factors"] = factors
                with self.assertRaisesRegex(ValueError, error):
                    Model.from_dict(case)
