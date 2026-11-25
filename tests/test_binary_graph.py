import json
from itertools import product
from math import prod
from pathlib import Path
import unittest

from graphweft.edge_study import compare_added_edge
from graphweft.model import Model
from graphweft.transport import compare

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class BinaryGraphTests(unittest.TestCase):
    def test_all_four_node_graphs_attain_the_coordinate_marginal_bound(self):
        nodes = ("A", "B", "C", "D")
        states = tuple(product((0, 1), repeat=4))
        source = (0.25, 0.75, 0.5, 0.375)
        target = (0.75, 0.25, 0.5, 0.125)
        bound = sum(abs(x - y) for x, y in zip(source, target))
        laws = {
            side: [prod(p if bit else 1 - p for p, bit in zip(rates, state)) for state in states]
            for side, rates in (("source", source), ("target", target))
        }
        edges = [(parent, child) for index, child in enumerate(nodes) for parent in nodes[:index]]
        for mask in product((0, 1), repeat=len(edges)):
            parents = {node: [] for node in nodes}
            for (parent, child), included in zip(edges, mask):
                if included:
                    parents[child].append(parent)
            with self.subTest(parents=parents):
                result = compare(Model.from_dict({"nodes": list(nodes), "parents": parents, **laws}))
                self.assertAlmostEqual(result["ordinary"]["cost"], bound)
                self.assertAlmostEqual(result["constrained"]["cost"], bound)
                self.assertTrue(result["constrained"]["audit"]["admissible"])

    def test_interior_collider_matches_full_enumeration_of_uniform_kernels(self):
        nodes = ["A", "B", "C", "D"]
        factors = {
            name: [[(13 * x + 7 * y + 3 * x * y + index * y) % 17 for y in range(size)] for x in range(size)]
            for index, (name, size) in enumerate(zip(nodes, (2, 2, 8, 16)))
        }
        model = Model.from_dict({
            "nodes": nodes, "parents": {"A": [], "B": [], "C": ["A", "B"], "D": ["A", "B", "C"]},
            "source": [0.0625] * 16, "target": [0.0625] * 16, "cost_factors": factors,
        })
        # Fair-bit extreme couplings are identities or flips. Given the upstream maps,
        # each source context corresponds to exactly one reachable paired context.
        lowest = float("inf")
        states = tuple(product((0, 1), repeat=4))
        for flip_a, flip_b, *flips in product((0, 1), repeat=14):
            total = 0
            for x, (a, b, c, d) in enumerate(states):
                y_a, y_b = a ^ flip_a, b ^ flip_b
                y_c = c ^ flips[2 * a + b]
                y_d = d ^ flips[4 + x // 2]
                y = 8 * y_a + 4 * y_b + 2 * y_c + y_d
                total += factors["A"][a][y_a] + factors["B"][b][y_b]
                total += factors["C"][x // 2][y // 2] + factors["D"][x][y]
            lowest = min(lowest, total / 16)
        result = compare(model)["constrained"]
        self.assertAlmostEqual(result["cost"], lowest)
        self.assertTrue(result["audit"]["admissible"])

    def test_adding_an_edge_between_two_nonperfect_graphs(self):
        case = json.loads((EXAMPLES / "four_node_collider.json").read_text())
        study = compare_added_edge(case, "A", "C")
        original = study["original"]["result"]
        expanded = study["expanded"]["result"]
        self.assertEqual((original["ordinary"]["cost"], original["constrained"]["cost"]), (0.25, 0.5))
        self.assertEqual(expanded["constrained"]["cost_by_node"], {"A": 0, "B": 0, "C": 0.25, "D": 0})
        self.assertEqual(study["cost_decrease"], 0.25)
        self.assertTrue(expanded["constrained"]["audit"]["admissible"])
        failure = study["original_graph_audit"]["failures"][0]
        self.assertEqual((failure["node"], failure["kind"]), ("C", "history_dependence"))
