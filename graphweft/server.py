import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from itertools import product

from .audit import audit_plan
from .edge_study import compare_added_edge, scan_added_edges, search_added_edges
from .experiments import MAX_RUN_BYTES, create_run, verify_run
from .model import Model
from .transport import compare

_MAX_BODY_BYTES = 64 * 1024
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def demo_examples():
    fork_nodes = ["A", "B", "C"]
    fork_edges = {"A": [], "B": ["A"], "C": ["A"]}
    fork_model = {
        "nodes": fork_nodes, "parents": fork_edges,
        "source": [0.5, 0, 0, 0, 0, 0, 0, 0.5], "target": [0.25] * 4 + [0] * 4,
    }
    collider_model = {
        "nodes": fork_nodes, "parents": {"A": [], "B": [], "C": ["A", "B"]},
        "source": [0.25, 0, 0, 0.25, 0, 0.25, 0.25, 0],
        "target": [0.25, 0, 0, 0.25, 0.25, 0, 0, 0.25],
        "cost_factors": {"C": [[2 if x % 2 != y % 2 else 0 for y in range(8)] for x in range(8)]},
    }
    shared_coin_plan = [
        [0.0625 if target in (source, source ^ 3) else 0 for target in range(8)]
        for source in range(8)
    ]
    return [
        {
            "id": "fork", "label": "Three-node fork", "operation": "compare",
            "model": fork_model,
        },
        {
            "id": "weighted-fork", "label": "Parent-weighted fork", "operation": "compare",
            "model": {**fork_model, "cost_factors": {"C": [
                [0, 2, 0, 2], [2, 0, 2, 0], [0, 4, 0, 4], [4, 0, 4, 0],
            ]}},
        },
        {
            "id": "chain", "label": "Two-node chain", "operation": "compare",
            "model": {
                "nodes": ["A", "B"], "parents": {"A": [], "B": ["A"]},
                "source": [0.5, 0, 0, 0.5], "target": [0.5, 0.5, 0, 0],
            },
        },
        {
            "id": "rare-state-chain", "label": "Rare-state chain", "operation": "compare",
            "model": {
                "nodes": ["A", "B"], "parents": {"A": [], "B": ["A"]},
                "source": [0.999999999999, 0, 0, 1e-12],
                "target": [0.999999999998, 0, 1e-12, 1e-12],
            },
        },
        {
            "id": "collider", "label": "Binary collider", "operation": "compare",
            "model": collider_model,
        },
        {
            "id": "ordered-control", "label": "Ordered control", "operation": "compare",
            "model": {**collider_model, "parents": {"A": [], "B": ["A"], "C": ["A", "B"]}},
        },
        {
            "id": "four-node-collider", "label": "Four-node collider", "operation": "compare",
            "model": {
                "nodes": [*fork_nodes, "D"],
                "parents": {"A": [], "B": [], "C": ["B"], "D": ["A", "B", "C"]},
                "source": [0.125 if d == a ^ b ^ c else 0 for a, b, c, d in product((0, 1), repeat=4)],
                "target": [0.125 if d == b ^ c else 0 for _, b, c, d in product((0, 1), repeat=4)],
                "cost_factors": {"C": [[0.5 if x % 2 != y % 2 else 0 for y in range(4)] for x in range(4)]},
            },
        },
        {
            "id": "interacting-edges", "label": "Interacting edges", "operation": "compare",
            "model": {
                "nodes": [*fork_nodes, "D"],
                "parents": {"A": [], "B": [], "C": [], "D": ["A", "B", "C"]},
                "source": [0.125 if d == a ^ b ^ c else 0 for a, b, c, d in product((0, 1), repeat=4)],
                "target": [0.125 if d == c else 0 for _, _, c, d in product((0, 1), repeat=4)],
                "cost_factors": {"C": [[0, 0.5], [0.5, 0]]},
            },
        },
        {
            "id": "shared-coin", "label": "Shared-coin audit", "operation": "audit",
            "model": {
                "nodes": fork_nodes, "parents": fork_edges,
                "source": [0.125] * 8, "target": [0.125] * 8,
            },
            "plan": shared_coin_plan,
        },
    ]


class WorkbenchHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(5)
        super().setup()

    def _send(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status, body):
        payload = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self._send(status, payload, "application/json; charset=utf-8")

    def _allow_local(self):
        host = f"127.0.0.1:{self.server.server_port}"
        origin = self.headers.get("Origin")
        if self.headers.get("Host") != host or (origin is not None and origin != f"http://{host}"):
            self._json(403, {"error": "Open GraphWeft at its local 127.0.0.1 address."})
            return False
        return True

    def do_GET(self):
        if not self._allow_local():
            return
        if self.path == "/api/examples":
            self._json(200, demo_examples())
        elif self.path in _ASSETS:
            filename, content_type = _ASSETS[self.path]
            asset = files("graphweft").joinpath("web").joinpath(filename).read_bytes()
            self._send(200, asset, content_type)
        else:
            self._json(404, {"error": "Page not found."})

    def do_POST(self):
        if not self._allow_local():
            return
        if self.path not in ("/api/compare", "/api/audit", "/api/run", "/api/replay", "/api/edge", "/api/edge-scan", "/api/edge-search"):
            self._json(404, {"error": "Operation not found."})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "Send an application/json request."})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        replay = self.path == "/api/replay"
        if size > (MAX_RUN_BYTES if replay else _MAX_BODY_BYTES):
            self._json(413, {"error": "Run files are limited to 1 MiB." if replay else "Input exceeds 64 KiB."})
            return
        try:
            data = json.loads(self.rfile.read(max(0, size)))
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, RecursionError):
            self._json(400, {"error": "Send a valid JSON object."})
            return

        try:
            if replay:
                result = verify_run(data)
            elif self.path == "/api/run":
                result = create_run(data)
            elif self.path == "/api/edge":
                result = compare_added_edge(data.get("model"), data.get("parent"), data.get("child"))
            elif self.path == "/api/edge-scan":
                result = scan_added_edges(data.get("model"))
            elif self.path == "/api/edge-search":
                result = search_added_edges(data.get("model"))
            else:
                model = Model.from_dict(data.get("model"))
                if self.path == "/api/compare":
                    result = compare(model)
                else:
                    plan = data.get("plan")
                    result = {"states": list(model.states), "plan": plan, "audit": audit_plan(model, plan)}
        except ValueError as error:
            self._json(422, {"error": str(error)})
        except RuntimeError:
            self._json(500, {"error": "The solver could not return a plan that passed its numerical checks."})
        else:
            self._json(200, result)


def serve(port):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    with ThreadingHTTPServer(("127.0.0.1", port), WorkbenchHandler) as server:
        print(f"GraphWeft is listening at http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
