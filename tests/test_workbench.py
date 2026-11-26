from concurrent.futures import ThreadPoolExecutor
from email.message import Message
import json
import unittest
from http.client import HTTPConnection, HTTPResponse
from http.server import ThreadingHTTPServer
from pathlib import Path
from socket import SHUT_WR, create_connection
from threading import Thread
from unittest.mock import Mock, patch

from graphweft.experiments import MAX_RUN_BYTES
from graphweft.server import WorkbenchHandler

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
JSON_HEADER = {"Content-Type": "application/json"}


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

    def framed_request(self, headers, body, finish=True, path="/api/run"):
        port = self.server.server_port
        request = f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\n"
        with create_connection(("127.0.0.1", port), timeout=3) as connection:
            connection.sendall((request + headers + "\r\n").encode("ascii") + body)
            if finish:
                connection.shutdown(SHUT_WR)
            with HTTPResponse(connection) as response:
                response.begin()
                return response.status, json.loads(response.read())

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
                              ("interacting-edges", "interacting_edges.json"),
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

    def test_ambiguous_json_is_rejected_before_dispatch(self):
        cases = (b'{"model":{},"model":{}}', b'{"unknown":NaN}', b'{"unknown":1e309}',
                 b'[' * 10_000 + b'0' + b']' * 10_000)
        for body in cases:
            with self.subTest(body=body[:40]):
                status, _, payload = self.request("POST", "/api/run", body, JSON_HEADER)
                self.assertEqual(status, 400)
                self.assertIn("JSON", json.loads(payload)["error"])

    def test_content_length_must_describe_one_complete_body(self):
        cases = (
            ("", "Content-Length"),
            ("Content-Length: -2\r\n", "Content-Length"),
            ("Content-Length: 2\r\nContent-Length: 2\r\n", "Content-Length"),
            ("Transfer-Encoding: chunked\r\n", "Content-Length"),
            ("Content-Length: 12\r\n", "ended before"),
        )
        for headers, message in cases:
            with self.subTest(headers=headers):
                status, payload = self.framed_request(headers, b"{}")
                self.assertEqual(status, 400)
                self.assertIn(message, payload["error"])
        status, _ = self.framed_request("Content-Length: " + "9" * 5000 + "\r\n", b"")
        self.assertEqual(status, 413)

    def test_stalled_request_body_times_out(self):
        def short_setup(handler):
            original_setup(handler)
            handler.request.settimeout(0.2)

        original_setup = WorkbenchHandler.setup
        with patch.object(WorkbenchHandler, "setup", short_setup):
            status, payload = self.framed_request("Content-Length: 12\r\n", b"{}", finish=False)
        self.assertEqual(status, 408)
        self.assertIn("Timed out", payload["error"])

    def test_disconnected_client_abandons_response(self):
        handler = object.__new__(WorkbenchHandler)
        handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
        handler.wfile = Mock()
        handler.wfile.write.side_effect = BrokenPipeError
        handler._send(200, b"{}", "application/json")
        self.assertTrue(handler.close_connection)

    def test_disconnected_client_abandons_request_before_solving(self):
        handler = object.__new__(WorkbenchHandler)
        handler.path = "/api/run"
        handler.headers = Message()
        handler.headers["Content-Type"] = "application/json"
        handler.headers["Content-Length"] = "20"
        handler._allow_local = Mock(return_value=True)
        handler.rfile = Mock()
        handler.rfile.read.side_effect = ConnectionResetError
        with patch("graphweft.server.create_run") as solve:
            handler.do_POST()
        self.assertTrue(handler.close_connection)
        solve.assert_not_called()

    def test_request_and_replay_size_limits(self):
        model = json.loads((EXAMPLES / "binary_chain.json").read_text())
        data = json.dumps({"operation": "compare", "model": model}).encode()
        status, _, result = self.request("POST", "/api/run", data.ljust(64 * 1024), JSON_HEADER)
        self.assertEqual(status, 200)
        status, _ = self.framed_request(f"Content-Length: {64 * 1024 + 1}\r\n", b"")
        self.assertEqual(status, 413)
        status, _, _ = self.request("POST", "/api/replay", result.ljust(MAX_RUN_BYTES), JSON_HEADER)
        self.assertEqual(status, 200)
        status, _ = self.framed_request(f"Content-Length: {MAX_RUN_BYTES + 1}\r\n", b"", path="/api/replay")
        self.assertEqual(status, 413)

    def test_solver_failure_returns_a_clean_error_and_the_next_request_succeeds(self):
        model = json.loads((EXAMPLES / "binary_chain.json").read_text())
        body = json.dumps({"operation": "compare", "model": model})
        with patch("graphweft.server.create_run", side_effect=RuntimeError("internal failure")):
            status, _, payload = self.request("POST", "/api/run", body, JSON_HEADER)
        self.assertEqual(status, 500)
        self.assertIn("numerical checks", json.loads(payload)["error"])
        self.assertNotIn(b"internal failure", payload)
        status, _, payload = self.request("POST", "/api/run", body, JSON_HEADER)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["result"]["cost_gap"], 0.5)

    def test_overlapping_requests_keep_models_and_costs_separate(self):
        fixtures = (("binary_chain.json", 1), ("binary_fork.json", 1.5), ("interacting_edges.json", 0.5))

        def run(request):
            filename, expected = request
            model = json.loads((EXAMPLES / filename).read_text())
            body = json.dumps({"operation": "compare", "model": model})
            status, _, payload = self.request("POST", "/api/run", body, JSON_HEADER)
            result = json.loads(payload)
            return status, result["input"]["model"] == model, result["result"]["constrained"]["cost"], expected

        with ThreadPoolExecutor(max_workers=6) as workers:
            results = list(workers.map(run, fixtures * 2))
        for status, same_input, cost, expected in results:
            self.assertEqual(status, 200)
            self.assertTrue(same_input)
            self.assertEqual(cost, expected)

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

    def test_edge_search_returns_a_verifiable_combination(self):
        model = json.loads((EXAMPLES / "interacting_edges.json").read_text())
        headers = {"Content-Type": "application/json"}
        status, _, payload = self.request("POST", "/api/edge-search", json.dumps({"model": model}), headers)
        self.assertEqual(status, 200)
        search = json.loads(payload)
        self.assertEqual(search["graphs_evaluated"], 8)
        self.assertEqual(search["minimum_edges_to_ordinary"], 2)
        run = search["best_additions"][1]["expanded"]
        self.assertEqual(run["input"]["model"]["parents"]["C"], ["A", "B"])
        status, _, payload = self.request("POST", "/api/replay", json.dumps(run), headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["result"]["constrained"]["cost"], 0.25)

        status, _, payload = self.request("POST", "/api/replay", json.dumps(search), headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload), search)
        search["minimum_edges_to_ordinary"] = 1
        status, _, payload = self.request("POST", "/api/replay", json.dumps(search), headers)
        self.assertEqual(status, 422)
        self.assertIn("minimum edges to ordinary", json.loads(payload)["error"])

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
