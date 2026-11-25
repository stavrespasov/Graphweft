import json
from itertools import product
from pathlib import Path
import unittest

from graphweft.audit import audit_plan
from graphweft.experiments import create_run, verify_run
from graphweft.model import Model

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "rare_state_chain.json"


def rare_chain(epsilon):
    spec = json.loads(FIXTURE.read_text())
    spec.update(source=[1 - epsilon, 0, 0, epsilon], target=[1 - 2 * epsilon, 0, epsilon, epsilon])
    return spec


class RareStateTests(unittest.TestCase):
    def test_rare_chain_preserves_masses_and_resolves_the_cost_gap(self):
        for epsilon in (1e-9, 1e-12, 1e-20, 1e-100):
            with self.subTest(epsilon=epsilon):
                run = create_run({"operation": "compare", "model": rare_chain(epsilon)})
                result = verify_run(run)["result"]
                # Ordinary OT moves epsilon from 00 to 10. The chain's target B must be
                # fair when target A=1, even conditional on paired A. This costs 2 epsilon.
                self.assertAlmostEqual(result["ordinary"]["cost"] / epsilon, 1.0)
                self.assertAlmostEqual(result["constrained"]["cost"] / epsilon, 2.0)
                self.assertAlmostEqual(result["cost_gap"] / epsilon, 1.0)
                for entry in (result["ordinary"], result["constrained"]):
                    self.assertAlmostEqual(sum(entry["plan"][3]) / epsilon, 1.0)
                self.assertTrue(result["constrained"]["audit"]["admissible"])
                self.assertFalse(result["ordinary"]["audit"]["admissible"])

    def test_audit_identifies_missing_and_unexpected_support_below_tolerance(self):
        epsilon = 1e-12
        model = Model.from_dict(rare_chain(epsilon))
        plan = [[0.0] * 4 for _ in range(4)]
        plan[0][0] = 1 - epsilon
        plan[1][2] = epsilon
        audit = audit_plan(model, plan)
        source, target = audit["failures"][:2]
        self.assertFalse(audit["admissible"])
        self.assertLess(source["max_absolute_error"], audit["absolute_tolerance"])
        self.assertEqual(source["missing_states"], ["11"])
        self.assertEqual(source["unexpected_states"], ["01"])
        self.assertEqual(target["missing_states"], ["11"])

    def test_rare_root_in_a_collider_preserves_the_constraint_cost(self):
        epsilon = 1e-20
        spec = json.loads((FIXTURE.parent / "binary_collider.json").read_text())
        source, target = [], []
        for a, b, c in product((0, 1), repeat=3):
            mass = (epsilon if a else 1 - epsilon) / 2
            source.append(mass if c == (a ^ b) else 0)
            target.append(mass if c == b else 0)
        spec.update(source=source, target=target)
        result = create_run({"operation": "compare", "model": spec})["result"]
        self.assertAlmostEqual(result["ordinary"]["cost"] / epsilon, 1.0)
        self.assertAlmostEqual(result["constrained"]["cost"] / epsilon, 2.0)
        self.assertTrue(result["constrained"]["audit"]["admissible"])

    def test_model_rejects_rare_support_incompatible_with_independence(self):
        spec = rare_chain(1e-12)
        spec["parents"]["B"] = []
        with self.assertRaisesRegex(ValueError, "source is incompatible"):
            Model.from_dict(spec)

    def test_audit_rejects_a_rare_state_with_the_wrong_positive_mass(self):
        spec = rare_chain(1e-12)
        spec["target"] = spec["source"][:]
        plan = [[0.0] * 4 for _ in range(4)]
        plan[0][0] = 1 - 1e-20
        plan[3][3] = 1e-20
        audit = audit_plan(Model.from_dict(spec), plan)
        self.assertFalse(audit["admissible"])
        for marginal in audit["failures"]:
            self.assertEqual(marginal["misweighted_states"], ["11"])
            self.assertLess(marginal["max_absolute_error"], audit["absolute_tolerance"])

    def test_replay_rejects_a_legacy_optimum_that_dropped_rare_mass(self):
        run = create_run({"operation": "compare", "model": rare_chain(1e-12)})
        run["manifest"]["scipy"] = "1.17.1"
        del run["manifest"]["networkx"]
        run["result"]["ordinary"]["plan"] = [[1, 0, 0, 0]] + [[0] * 4 for _ in range(3)]
        with self.assertRaisesRegex(ValueError, "saved ordinary plan fails its feasibility checks"):
            verify_run(run)

    def test_replay_adds_state_diagnostics_to_a_legacy_audit(self):
        run = create_run({"operation": "audit", "model": rare_chain(1e-12), "plan": [[0] * 4 for _ in range(4)]})
        run["manifest"]["scipy"] = "1.17.1"
        del run["manifest"]["networkx"]
        for failure in run["result"]["audit"]["failures"]:
            del failure["missing_states"]
        verified = verify_run(run)
        self.assertEqual(verified["result"]["audit"]["failures"][0]["missing_states"], ["00", "11"])
