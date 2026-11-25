import argparse
import json
import sys
from pathlib import Path

from .audit import audit_plan
from .model import Model
from .transport import compare


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


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
    parser = argparse.ArgumentParser(description="Compare Hamming transport plans and audit graph-bicausality.")
    commands = parser.add_subparsers(dest="command", required=True)
    browser = commands.add_parser("serve", help="open a local browser workbench")
    browser.add_argument("--port", type=int, default=8765, help="loopback port (default: 8765)")
    for name, help_text in (
        ("compare", "solve ordinary and graph-bicausal transport"),
        ("audit", "test a supplied coupling against the graph"),
    ):
        subparser = commands.add_parser(name, help=help_text)
        subparser.add_argument("model", help="JSON model file")
        if name == "audit":
            subparser.add_argument("plan", help="JSON coupling matrix")
        subparser.add_argument("--summary", action="store_true", help="show costs and the first violation")

    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve

            serve(args.port)
            return 0
        model = Model.from_dict(read_json(args.model))
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
                    result[mode] = {"cost": entry["cost"], "audit": summarize(entry["audit"])}
        print(json.dumps(result, indent=2, allow_nan=False))
        return status
    except (OSError, ValueError, RuntimeError) as error:
        print(f"graphweft: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
