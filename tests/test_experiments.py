import copy
import json
from pathlib import Path
import unittest

import numpy as np

from graphweft.audit import audit_plan
from graphweft.experiments import RUN_SCHEMA, create_run, verify_run
from graphweft.model import Model
from graphweft.transport import hamming_costs

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text())


def compare_example(name="binary_chain.json"):
    return create_run({"operation": "compare", "model": load(name)})


class RunFileTests(unittest.TestCase):
    def test_comparison_round_trip_accepts_browser_numeric_encoding(self):
        saved = compare_example()
        # JSON.stringify emits integral numeric values without a fractional suffix.
        browser_run = json.loads(json.dumps(saved, sort_keys=True), parse_float=lambda text: (
            int(float(text)) if float(text).is_integer() else float(text)
        ))
        verified = verify_run(browser_run)
        self.assertEqual(verified["schema"], RUN_SCHEMA)
        self.assertEqual(verified["manifest"], saved["manifest"])
        self.assertEqual(verified["result"], saved["result"])

    def test_alternative_optimal_plan_is_preserved(self):
        saved = compare_example("binary_fork.json")
        model = Model.from_dict(saved["input"]["model"])
        alternatives = []
        for selector in (1, 2):
            matrix = [[0.0] * 8 for _ in range(8)]
            for target, state in enumerate(model.states[:4]):
                source = 7 if state[selector] == "1" else 0
                matrix[source][target] = 0.25
            alternatives.append(matrix)
        alternative = next(plan for plan in alternatives if plan != saved["result"]["ordinary"]["plan"])
        saved["result"]["ordinary"]["plan"] = alternative
        saved["result"]["ordinary"]["audit"] = audit_plan(model, alternative)
        verified = verify_run(saved)
        self.assertEqual(verified["result"]["ordinary"]["plan"], alternative)

    def test_rejects_changed_inputs_costs_audits_and_schema(self):
        original = compare_example()
        for error, section, field, changed in (
            ("format", (), "schema", "unsupported"),
            ("checksum", ("input", "model"), "target", [0.25, 0.75, 0, 0]),
            ("cost does not match", ("result", "ordinary"), "cost", 0),
            ("audit does not match", ("result", "ordinary", "audit"), "admissible", True),
            ("state order", ("result",), "states", ["00"]),
        ):
            with self.subTest(error=error):
                edited = copy.deepcopy(original)
                container = edited
                for key in section:
                    container = container[key]
                container[field] = changed
                with self.assertRaisesRegex(ValueError, error):
                    verify_run(edited)

    def test_feasible_but_nonoptimal_plan_fails_verification(self):
        saved = compare_example()
        model = Model.from_dict(saved["input"]["model"])
        independent = np.outer(model.source, model.target)
        saved["result"]["ordinary"] = {
            "plan": independent.tolist(), "audit": audit_plan(model, independent),
            "cost": float((independent * hamming_costs(model)).sum()),
        }
        saved["result"]["cost_gap"] = 0
        with self.assertRaisesRegex(ValueError, "recomputed optimum"):
            verify_run(saved)

    def test_audit_can_verify_an_inadmissible_plan(self):
        saved = create_run({
            "operation": "audit", "model": load("shared_coin_model.json"),
            "plan": load("shared_coin_plan.json"),
        })
        confirmed = verify_run(json.loads(json.dumps(saved)))
        self.assertFalse(confirmed["result"]["audit"]["admissible"])
        self.assertEqual(confirmed["result"]["audit"]["failures"][0]["node"], "C")
        saved["result"]["audit"]["failures"][0]["observed"] = [0.25] * 4
        with self.assertRaisesRegex(ValueError, "saved audit"):
            verify_run(saved)
