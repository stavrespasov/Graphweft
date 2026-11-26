import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from io import BufferedReader, RawIOBase
from itertools import product
from threading import BoundedSemaphore
from time import monotonic

from .audit import audit_plan
from .edge_study import compare_added_edge, scan_added_edges, search_added_edges
from .experiments import MAX_RUN_BYTES, create_run, verify_saved_document
from .json_io import decode_json
from .model import Model
from .transport import compare

_MAX_BODY_BYTES = 64 * 1024
_MAX_CONNECTIONS = 16
_MAX_SOLVES = 4
_BUSY_BODY = b'{"error":"Too many open workbench connections. Try again shortly."}'
_BUSY_RESPONSE = (
    b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\n"
    b"Connection: close\r\nRetry-After: 1\r\nCache-Control: no-store\r\nContent-Length: "
    + str(len(_BUSY_BODY)).encode("ascii") + b"\r\n\r\n" + _BUSY_BODY
)
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


class _DeadlineReader(RawIOBase):
    def __init__(self, connection, deadline):
        super().__init__()
        self.connection = connection
        self.deadline = deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Request input deadline expired")
        self.connection.settimeout(remaining)
        return self.connection.recv_into(buffer)


class WorkbenchHandler(BaseHTTPRequestHandler):
    request_timeout = 5

    def setup(self):
        super().setup()
        self.rfile.close()
        self.rfile = BufferedReader(_DeadlineReader(self.connection, monotonic() + self.request_timeout))

    def _send(self, status, content, content_type, retry_after=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )
        try:
            self.connection.settimeout(self.request_timeout)
            self.end_headers()
            self.wfile.write(content)
        except (ConnectionError, TimeoutError):
            self.close_connection = True

    def _json(self, status, body, retry_after=None):
        payload = json.dumps(body, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self._send(status, payload, "application/json; charset=utf-8", retry_after)

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
        elif self.path == "/api/startup":
            self._json(200, {"examples": demo_examples(), "initial_run": self.server.initial_run})
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
        replay = self.path == "/api/replay"
        limit = MAX_RUN_BYTES if replay else _MAX_BODY_BYTES
        lengths = self.headers.get_all("Content-Length", [])
        length = lengths[0].strip() if len(lengths) == 1 else ""
        if self.headers.get("Transfer-Encoding") is not None or not length.isascii() or not length.isdigit():
            self._json(400, {"error": "Send a single valid Content-Length for the JSON body."})
            return
        digits = length.lstrip("0") or "0"
        if len(digits) > len(str(limit)) or int(digits) > limit:
            self._json(413, {"error": "Run files are limited to 1 MiB." if replay else "Input exceeds 64 KiB."})
            return
        size = int(digits)
        try:
            contents = self.rfile.read(size)
        except TimeoutError:
            self._json(408, {"error": "Timed out waiting for the JSON request body."})
            return
        except ConnectionError:
            self.close_connection = True
            return
        if len(contents) != size:
            self._json(400, {"error": "The JSON request body ended before the stated length."})
            return
        try:
            data = decode_json(contents)
        except ValueError as error:
            self._json(400, {"error": f"Invalid JSON. {error}"})
            return
        if not isinstance(data, dict):
            self._json(400, {"error": "Send a valid JSON object."})
            return

        if not self.server.solve_slots.acquire(blocking=False):
            self._json(503, {"error": "The workbench is busy solving other requests. Try again shortly."}, retry_after=1)
            return
        try:
            status, result = 200, self._run_operation(data)
        except ValueError as error:
            status, result = 422, {"error": str(error)}
        except RuntimeError:
            status, result = 500, {"error": "The solver could not return a plan that passed its numerical checks."}
        finally:
            self.server.solve_slots.release()
        self._json(status, result)

    def _run_operation(self, data):
        if self.path == "/api/replay":
            return verify_saved_document(data)
        if self.path == "/api/run":
            return create_run(data)
        if self.path == "/api/edge":
            return compare_added_edge(data.get("model"), data.get("parent"), data.get("child"))
        if self.path == "/api/edge-scan":
            return scan_added_edges(data.get("model"))
        if self.path == "/api/edge-search":
            return search_added_edges(data.get("model"))
        model = Model.from_dict(data.get("model"))
        if self.path == "/api/compare":
            return compare(model)
        plan = data.get("plan")
        return {"states": list(model.states), "plan": plan, "audit": audit_plan(model, plan)}


class WorkbenchServer(ThreadingHTTPServer):
    request_queue_size = _MAX_CONNECTIONS

    def __init__(
        self, address, handler=WorkbenchHandler, *,
        max_connections=_MAX_CONNECTIONS, max_solves=_MAX_SOLVES, initial_run=None,
    ):
        self.connection_slots = BoundedSemaphore(max_connections)
        self.solve_slots = BoundedSemaphore(max_solves)
        self.initial_run = initial_run
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(blocking=False):
            try:
                request.settimeout(0.1)
                request.sendall(_BUSY_RESPONSE)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()


def serve(port, *, initial_run=None):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    with WorkbenchServer(("127.0.0.1", port), initial_run=initial_run) as server:
        print(f"GraphWeft is listening at http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
