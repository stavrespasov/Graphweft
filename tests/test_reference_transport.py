import json
from itertools import combinations, product
from math import prod
from pathlib import Path
from random import Random
import unittest

import numpy as np

from graphweft.edge_study import search_added_edges
from graphweft.model import Model
from graphweft.transport import compare
from reference_transport import reference_optima

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _case(nodes, parents, rng, rates):
    specification = {"nodes": nodes, "parents": parents}
    states = tuple(product((0, 1), repeat=len(nodes)))
    axes = [tuple(nodes.index(parent) for parent in parents[node]) for node in nodes]
    for side in ("source", "target"):
        kernels = [
            {bits: rng.choice(rates) for bits in product((0, 1), repeat=len(past))}
            for past in axes
        ]
        law = []
        for state in states:
            probabilities = (row[tuple(state[j] for j in past)] for row, past in zip(kernels, axes))
            law.append(prod(p if bit else 1 - p for bit, p in zip(state, probabilities)))
        specification[side] = law

    specification["cost_factors"] = {}
    for node, past in zip(nodes, axes):
        size = 2 ** (len(past) + 1)
        specification["cost_factors"][node] = [[rng.randrange(17) for _ in range(size)] for _ in range(size)]
    return specification


class ReferenceTransportTests(unittest.TestCase):
    def assert_reference_matches(self, specification):
        ordinary, constrained, local_costs = reference_optima(specification)
        result = compare(Model.from_dict(specification))
        for key, expected in (("ordinary", ordinary), ("constrained", constrained)):
            plan = np.asarray(result[key]["plan"])
            np.testing.assert_allclose(plan.sum(axis=1), specification["source"], rtol=1e-10, atol=0)
            np.testing.assert_allclose(plan.sum(axis=0), specification["target"], rtol=1e-10, atol=0)
            for node, costs in zip(specification["nodes"], local_costs):
                self.assertAlmostEqual(float((costs * plan).sum()), result[key]["cost_by_node"][node], places=8)
            self.assertAlmostEqual(float((local_costs * plan).sum()), expected, places=8)
            self.assertAlmostEqual(result[key]["cost"], expected, places=8)
        self.assertTrue(result["constrained"]["audit"]["admissible"])
        return ordinary, constrained

    def test_four_node_solvers_against_full_coupling_reference(self):
        nodes = list("ABCD")
        edges = [(parent, child) for index, child in enumerate(nodes) for parent in nodes[:index]]
        rng = Random(8192)
        for mask in product((0, 1), repeat=len(edges)):
            parents = {node: [] for node in nodes}
            for (parent, child), present in zip(edges, mask):
                if present:
                    parents[child].append(parent)
            for rates in ((0.25, 0.5, 0.75), (0, 0.25, 0.5, 0.75, 1)):
                with self.subTest(edges=mask, rates=rates):
                    specification = _case(nodes, parents, rng, rates)
                    self.assert_reference_matches(specification)

    def test_published_fixtures_have_the_expected_reference_optima(self):
        cases = {
            "binary_chain.json": (0.5, 1),
            "binary_fork.json": (1, 1.5),
            "parent_weighted_fork.json": (1, 2.5),
            "binary_collider.json": (0.5, 1),
            "ordered_control.json": (0.5, 0.5),
            "four_node_collider.json": (0.25, 0.5),
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                specification = json.loads((EXAMPLES / filename).read_text())
                observed = self.assert_reference_matches(specification)
                np.testing.assert_allclose(observed, expected, rtol=0, atol=1e-10)

    def test_interacting_edges_search_matches_reference_over_all_subsets(self):
        specification = json.loads((EXAMPLES / "interacting_edges.json").read_text())
        candidates = (("A", "B"), ("A", "C"), ("B", "C"))
        reference_by_count = []
        for count in range(len(candidates) + 1):
            costs = []
            for added in combinations(candidates, count):
                parents = {node: past[:] for node, past in specification["parents"].items()}
                for parent, child in added:
                    parents[child].append(parent)
                size = 2 ** (len(parents["C"]) + 1)
                # The fixture charges 0.5 for a mismatch at C in every parent context.
                factor = [[0.5 if x % 2 != y % 2 else 0 for y in range(size)] for x in range(size)]
                expanded = {**specification, "parents": parents, "cost_factors": {"C": factor}}
                ordinary, constrained, _ = reference_optima(expanded)
                self.assertAlmostEqual(ordinary, 0.25)
                costs.append(constrained)
            reference_by_count.append(min(costs))

        result = search_added_edges(specification)
        actual = [result["original"]["result"]["constrained"]["cost"]]
        actual.extend(study["expanded"]["result"]["constrained"]["cost"] for study in result["best_additions"])
        np.testing.assert_allclose(actual, reference_by_count, rtol=0, atol=1e-10)
