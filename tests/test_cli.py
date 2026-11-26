from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from graphweft.__main__ import main
from graphweft.experiments import MAX_RUN_BYTES, create_run
from graphweft.json_io import MAX_JSON_DEPTH

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
STUDY = EXAMPLES.parent / "studies" / "bike_sharing"


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([str(argument) for argument in arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_audit_distinguishes_failed_condition_from_input_error(self):
        code, stdout, stderr = self.run_cli(
            "audit", EXAMPLES / "shared_coin_model.json", EXAMPLES / "shared_coin_plan.json", "--summary",
        )
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout)["admissible"])
        self.assertEqual(stderr, "")
        code, stdout, stderr = self.run_cli("audit", EXAMPLES / "shared_coin_model.json", EXAMPLES / "missing.json")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("missing.json", stderr)

    def test_invalid_documents_return_an_error_without_partial_output(self):
        problems = (
            (b'{"nodes":[],"nodes":["A"]}', "Duplicate JSON key"),
            (b'{"unused": NaN}', "must be finite"),
            (b'{"unused": 1e309}', "must be finite"),
            (b'[' * 10_000 + b'0' + b']' * 10_000, "nested too deeply"),
            (b'{"nodes": [', "Expecting"),
            (b'\xff\xff\xff', "decode"),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            for contents, expected in problems:
                with self.subTest(expected=expected):
                    path.write_bytes(contents)
                    code, stdout, stderr = self.run_cli("compare", path)
                    self.assertEqual(code, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn(expected, stderr)
                    self.assertNotIn("Traceback", stderr)

    def test_saved_run_size_limit_is_inclusive(self):
        model = json.loads((EXAMPLES / "binary_chain.json").read_text())
        run = json.dumps(create_run({"operation": "compare", "model": model})).encode()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "run.json"
            path.write_bytes(run.ljust(MAX_RUN_BYTES))
            code, stdout, _ = self.run_cli("verify-run", path)
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(stdout)["verified"])
            with path.open("ab") as output:
                output.write(b" ")
            code, stdout, stderr = self.run_cli("verify-run", path)
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn("1 MiB", stderr)

    def test_document_nesting_has_the_same_boundary_across_python_releases(self):
        model = b'{"nodes":["A"],"parents":{"A":[]},"source":[1,0],"target":[1,0],"extra":'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            for nesting, expected in ((MAX_JSON_DEPTH - 1, 0), (MAX_JSON_DEPTH, 2)):
                with self.subTest(nesting=nesting):
                    path.write_bytes(model + b'[' * nesting + b'0' + b']' * nesting + b'}')
                    code, stdout, stderr = self.run_cli("compare", path)
                    self.assertEqual(code, expected)
                    if expected == 0:
                        self.assertEqual(json.loads(stdout)["cost_gap"], 0)
                    else:
                        self.assertIn("nested too deeply", stderr)

    def test_invalid_ports_are_rejected_before_opening_a_socket(self):
        for port in ("0", "-1", "65536"):
            with self.subTest(port=port):
                code, stdout, stderr = self.run_cli("serve", "--port", port)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("Port must be between", stderr)

    def test_serve_passes_both_saved_report_formats_to_the_workbench(self):
        for filename in ("chain-search.json", "full-history-run.json"):
            with self.subTest(filename=filename), patch("graphweft.server.serve") as serve:
                path = STUDY / filename
                code, stdout, stderr = self.run_cli("serve", "--port", 4321, "--run", path)
                self.assertEqual((code, stdout, stderr), (0, "", ""))
                serve.assert_called_once()
                self.assertEqual(serve.call_args.args, (4321,))
                saved = json.loads(path.read_text())
                initial = serve.call_args.kwargs["initial_run"]
                self.assertEqual(initial["schema"], saved["schema"])
                if filename == "chain-search.json":
                    self.assertEqual(initial["graphs_evaluated"], 2)
                else:
                    self.assertAlmostEqual(initial["result"]["constrained"]["cost"], 1.5599365872009)

    def test_serve_rejects_a_tampered_run_before_starting_the_server(self):
        saved = json.loads((STUDY / "chain-search.json").read_text())
        saved["minimum_edges_to_ordinary"] = 1
        with TemporaryDirectory() as directory, patch("graphweft.server.serve") as serve:
            path = Path(directory) / "tampered.json"
            path.write_text(json.dumps(saved))
            code, stdout, stderr = self.run_cli("serve", "--run", path)
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn("incorrect minimum edges to ordinary", stderr)
            serve.assert_not_called()
