import json
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from graphweft.server import WorkbenchHandler

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), WorkbenchHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()

    def test_assets_and_packaged_examples(self):
        for path, expected_type in (
            ("/", "text/html"), ("/app.js", "text/javascript"), ("/styles.css", "text/css")
        ):
            status, content_type, payload = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertTrue(content_type.startswith(expected_type))
            self.assertGreater(len(payload), 100)
        status, _, payload = self.request("GET", "/api/examples")
        self.assertEqual(status, 200)
        examples = {entry["id"]: entry for entry in json.loads(payload)}
        for key, filename in (("fork", "binary_fork.json"), ("weighted-fork", "parent_weighted_fork.json"),
                              ("chain", "binary_chain.json"), ("rare-state-chain", "rare_state_chain.json"),
                              ("collider", "binary_collider.json"),
                              ("ordered-control", "ordered_control.json"),
                              ("four-node-collider", "four_node_collider.json"),
                              ("shared-coin", "shared_coin_model.json")):
            self.assertEqual(examples[key]["model"], json.loads((EXAMPLES / filename).read_text()))
        self.assertEqual(examples["shared-coin"]["plan"], json.loads((EXAMPLES / "shared_coin_plan.json").read_text()))

    def test_compare_and_audit_share_the_solver_contract(self):
        status, _, payload = self.request("GET", "/api/examples")
        self.assertEqual(status, 200)
        examples = {entry["id"]: entry for entry in json.loads(payload)}
        headers = {"Content-Type": "application/json"}
        status, _, payload = self.request(
            "POST", "/api/compare", json.dumps({"model": examples["fork"]["model"]}), headers
        )
        self.assertEqual(status, 200)
        result = json.loads(payload)
        self.assertEqual((result["ordinary"]["cost"], result["constrained"]["cost"]), (1, 1.5))
        self.assertTrue(result["constrained"]["audit"]["admissible"])

        counterexample = examples["shared-coin"]
        status, _, payload = self.request("POST", "/api/audit", json.dumps(counterexample), headers)
        self.assertEqual(status, 200)
        audit = json.loads(payload)["audit"]
        self.assertFalse(audit["admissible"])
        finding = audit["failures"][0]
        self.assertEqual(finding["node"], "C")
        self.assertEqual(finding["observed"], [0.5, 0, 0, 0.5])
        self.assertEqual(finding["required"], [0.25] * 4)

    def test_invalid_requests_return_actionable_errors(self):
        json_header = {"Content-Type": "application/json"}
        cases = [
            ("{}", {"Host": "example.com", **json_header}, 403),
            ("{}", {"Origin": "https://example.com", **json_header}, 403),
            ("{}", {"Content-Type": "text/plain"}, 415),
            (" " * (64 * 1024 + 1), json_header, 413),
            ("[", json_header, 400),
            ("{}", json_header, 422),
        ]
        for body, headers, expected in cases:
            with self.subTest(status=expected, headers=headers):
                status, _, payload = self.request("POST", "/api/compare", body, headers)
                self.assertEqual(status, expected)
                self.assertTrue(json.loads(payload)["error"])

        status, _, _ = self.request("GET", "/missing")
        self.assertEqual(status, 404)

    def test_edge_comparison_returns_the_cross_audit_and_expanded_run(self):
        model = json.loads((EXAMPLES / "binary_collider.json").read_text())
        headers = {"Content-Type": "application/json"}
        status, _, payload = self.request("POST", "/api/edge", json.dumps({
            "model": model, "parent": "A", "child": "B",
        }), headers)
        self.assertEqual(status, 200)
        study = json.loads(payload)
        self.assertEqual(study["cost_decrease"], 0.5)
        self.assertEqual(study["original_graph_audit"]["failures"][0]["node"], "B")
        status, _, payload = self.request("POST", "/api/replay", json.dumps(study["expanded"]), headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["input"]["model"]["parents"]["B"], ["A"])

    def test_edge_scan_returns_ranked_plans_that_can_be_replayed(self):
        model = json.loads((EXAMPLES / "four_node_collider.json").read_text())
        headers = {"Content-Type": "application/json"}
        status, _, payload = self.request("POST", "/api/edge-scan", json.dumps({"model": model}), headers)
        self.assertEqual(status, 200)
        scan = json.loads(payload)
        self.assertEqual([study["edge"] for study in scan["edges"]], [["A", "C"], ["A", "B"]])
        best = scan["edges"][0]
        self.assertEqual(best["original_graph_audit"]["failures"][0]["node"], "C")
        status, _, payload = self.request("POST", "/api/replay", json.dumps(best["expanded"]), headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["result"]["constrained"]["cost"], 0.25)

    def test_run_can_be_saved_and_replayed(self):
        model = json.loads((EXAMPLES / "binary_chain.json").read_text())
        headers = {"Content-Type": "application/json"}
        status, _, payload = self.request("POST", "/api/run", json.dumps({
            "operation": "compare", "model": model,
        }), headers)
        self.assertEqual(status, 200)
        run = json.loads(payload)
        self.assertEqual(run["result"]["cost_gap"], 0.5)

        status, _, payload = self.request("POST", "/api/replay", json.dumps(run), headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload), run)
        run["result"]["cost_gap"] = 1.5
        status, _, payload = self.request("POST", "/api/replay", json.dumps(run), headers)
        self.assertEqual(status, 422)
        self.assertIn("cost gap", json.loads(payload)["error"])
