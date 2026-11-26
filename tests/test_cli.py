from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from graphweft.__main__ import main
from graphweft.experiments import MAX_RUN_BYTES, create_run

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


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

    def test_invalid_ports_are_rejected_before_opening_a_socket(self):
        for port in ("0", "-1", "65536"):
            with self.subTest(port=port):
                code, stdout, stderr = self.run_cli("serve", "--port", port)
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("Port must be between", stderr)
