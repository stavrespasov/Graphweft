import argparse
import json
import sys
from pathlib import Path

from .audit import audit_plan
from .edge_study import compare_added_edge, scan_added_edges, search_added_edges
from .experiments import MAX_RUN_BYTES, verify_run
from .model import Model
from .transport import compare


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_run(path):
    with Path(path).open("rb") as source:
        contents = source.read(MAX_RUN_BYTES + 1)
    if len(contents) > MAX_RUN_BYTES:
        raise ValueError("Run files are limited to 1 MiB.")
    try:
        return json.loads(contents)
    except RecursionError:
        raise ValueError("The run file is nested too deeply.") from None


def summarize(report):
    failures = report["failures"]
    return {
        "admissible": report["admissible"],
        "failure_count": len(failures),
        "first_failure": failures[0] if failures else None,
        "bit_outcome_order": report["bit_outcome_order"],
        "pair_outcome_order": report["pair_outcome_order"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare graph-separable transport plans and audit graph-bicausality.")
    commands = parser.add_subparsers(dest="command", required=True)
    browser = commands.add_parser("serve", help="open a local browser workbench")
    browser.add_argument("--port", type=int, default=8765, help="loopback port (default: 8765)")
    verification = commands.add_parser("verify-run", help="recheck the claims in a saved run")
    verification.add_argument("file", help="GraphWeft run JSON file")
    for name, help_text in (
        ("compare", "solve ordinary and graph-bicausal transport"),
        ("compare-edge", "compare transport before and after adding a forward edge"),
        ("scan-edges", "rank all missing forward edges by their effect on transport cost"),
        ("search-edges", "find the best combination for each number of added edges"),
        ("audit", "test a supplied coupling against the graph"),
    ):
        subparser = commands.add_parser(name, help=help_text)
        subparser.add_argument("model", help="JSON model file")
        if name == "audit":
            subparser.add_argument("plan", help="JSON coupling matrix")
        if name == "compare-edge":
            subparser.add_argument("parent", help="node at the start of the new edge")
            subparser.add_argument("child", help="node at the end of the new edge")
        subparser.add_argument("--summary", action="store_true", help="show costs and audit summaries")

    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve

            serve(args.port)
            return 0
        if args.command == "verify-run":
            run = verify_run(read_run(args.file))
            operation = run["input"]["operation"]
            result = {"verified": True, "operation": operation, "input_sha256": run["manifest"]["input_sha256"]}
            if operation == "compare":
                result["costs"] = {name: run["result"][name]["cost"] for name in ("ordinary", "constrained")}
            else:
                result["admissible"] = run["result"]["audit"]["admissible"]
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0
        specification = read_json(args.model)
        if args.command == "compare-edge":
            result = compare_added_edge(specification, args.parent, args.child)
            if args.summary:
                before, after = (result[key]["result"] for key in ("original", "expanded"))
                result = {
                    "edge": result["edge"],
                    "ordinary_cost": before["ordinary"]["cost"],
                    "original_constrained_cost": before["constrained"]["cost"],
                    "expanded_constrained_cost": after["constrained"]["cost"],
                    "cost_decrease": result["cost_decrease"],
                    "original_graph_audit": summarize(result["original_graph_audit"]),
                }
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0
        if args.command == "scan-edges":
            result = scan_added_edges(specification)
            if args.summary:
                original = result["original"]["result"]
                result = {
                    "ordinary_cost": original["ordinary"]["cost"],
                    "original_constrained_cost": original["constrained"]["cost"],
                    "edges": [
                        {
                            "edge": study["edge"],
                            "expanded_constrained_cost": study["expanded"]["result"]["constrained"]["cost"],
                            "cost_decrease": study["cost_decrease"],
                            "original_graph_audit_passed": study["original_graph_audit"]["admissible"],
                        }
                        for study in result["edges"]
                    ],
                }
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0
        if args.command == "search-edges":
            result = search_added_edges(specification)
            if args.summary:
                original = result["original"]["result"]
                rows = [{"added_edges": [], "constrained_cost": original["constrained"]["cost"], "cost_decrease": 0.0}]
                rows.extend({
                    "added_edges": study["added_edges"],
                    "constrained_cost": study["expanded"]["result"]["constrained"]["cost"],
                    "cost_decrease": study["cost_decrease"],
                } for study in result["best_additions"])
                result = {
                    "graphs_evaluated": result["graphs_evaluated"],
                    "ordinary_cost": original["ordinary"]["cost"],
                    "minimum_edges_to_ordinary": result["minimum_edges_to_ordinary"],
                    "best_by_edge_count": rows,
                }
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0
        model = Model.from_dict(specification)
        status = 0
        if args.command == "audit":
            report = audit_plan(model, read_json(args.plan))
            result = summarize(report) if args.summary else report
            status = 0 if report["admissible"] else 1
        else:
            result = compare(model)
            if args.summary:
                for mode in ("ordinary", "constrained"):
                    entry = result[mode]
                    result[mode] = {
                        "cost": entry["cost"], "cost_by_node": entry["cost_by_node"],
                        "audit": summarize(entry["audit"]),
                    }
        print(json.dumps(result, indent=2, allow_nan=False))
        return status
    except (OSError, ValueError, RuntimeError) as error:
        print(f"graphweft: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
