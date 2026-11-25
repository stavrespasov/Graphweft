import hashlib
import json
import math
import platform

import numpy as np
import scipy

from .audit import audit_plan
from .model import AUDIT_TOLERANCE, Model, probability_array
from .transport import compare, hamming_costs

RUN_SCHEMA = "graphweft.run/1"
MAX_RUN_BYTES = 1024 * 1024


def _prepare(request):
    if not isinstance(request, dict) or request.get("operation") not in ("compare", "audit"):
        raise ValueError("A run must specify a compare or audit operation.")
    operation = request["operation"]
    specification = request.get("model")
    model = Model.from_dict(specification)
    payload = {
        "operation": operation,
        "model": {
            "nodes": list(model.nodes),
            "parents": {
                name: [model.nodes[parent] for parent in model.parents[index]]
                for index, name in enumerate(model.nodes)
            },
            # Retain the supplied weights before the solver's normalization.
            "source": [float(value) + 0.0 for value in specification["source"]],
            "target": [float(value) + 0.0 for value in specification["target"]],
        },
    }
    if operation == "audit":
        dimension = len(model.source)
        plan = probability_array(request.get("plan"), (dimension, dimension), "coupling")
        payload["plan"] = (plan + 0.0).tolist()
    return model, payload


def _digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _manifest(payload):
    return {
        "input_sha256": _digest(payload),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }


def create_run(request):
    model, payload = _prepare(request)
    if payload["operation"] == "compare":
        result = compare(model)
    else:
        plan = payload["plan"]
        result = {"states": list(model.states), "plan": plan, "audit": audit_plan(model, plan)}
    return {"schema": RUN_SCHEMA, "input": payload, "result": result, "manifest": _manifest(payload)}


def _same_evidence(expected, claimed):
    if isinstance(expected, float):
        if type(claimed) not in (int, float):
            return False
        try:
            return math.isclose(expected, claimed, abs_tol=AUDIT_TOLERANCE, rel_tol=0)
        except OverflowError:
            return False
    if isinstance(expected, list):
        return isinstance(claimed, list) and len(expected) == len(claimed) and all(
            _same_evidence(a, b) for a, b in zip(expected, claimed)
        )
    if isinstance(expected, dict):
        return isinstance(claimed, dict) and expected.keys() == claimed.keys() and all(
            _same_evidence(value, claimed[key]) for key, value in expected.items()
        )
    return type(expected) is type(claimed) and expected == claimed


def _verify_comparison(model, saved):
    reference = compare(model)
    costs = hamming_costs(model)
    result = {"states": list(model.states)}
    for name in ("ordinary", "constrained"):
        claim = saved.get(name)
        if not isinstance(claim, dict):
            raise ValueError(f"The saved run is missing its {name} plan.")
        plan = probability_array(claim.get("plan"), costs.shape, f"{name} coupling")
        audit = audit_plan(model, plan)
        marginal_failure = any(failure["kind"] == "joint_marginal" for failure in audit["failures"])
        if marginal_failure or (name == "constrained" and not audit["admissible"]):
            raise ValueError(f"The saved {name} plan fails its feasibility checks.")
        cost = float((plan * costs).sum())
        if not _same_evidence(cost, claim.get("cost")):
            raise ValueError(f"The saved {name} cost does not match its plan.")
        if not _same_evidence(reference[name]["cost"], cost):
            raise ValueError(f"The saved {name} cost does not match the recomputed optimum.")
        if not _same_evidence(audit, claim.get("audit")):
            raise ValueError(f"The saved {name} audit does not match its plan.")
        result[name] = {"plan": plan.tolist(), "cost": cost, "audit": audit}

    gap = result["constrained"]["cost"] - result["ordinary"]["cost"]
    if not _same_evidence(gap, saved.get("cost_gap")):
        raise ValueError("The saved cost gap does not match the verified costs.")
    result["cost_gap"] = gap
    return result


def verify_run(document):
    if not isinstance(document, dict) or document.get("schema") != RUN_SCHEMA:
        raise ValueError("This file does not use the supported GraphWeft run format.")
    model, payload = _prepare(document.get("input"))
    manifest = document.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("input_sha256") != _digest(payload):
        raise ValueError("The run's input checksum does not match its model and operation.")
    versions = ("python", "numpy", "scipy")
    if any(not isinstance(manifest.get(name), str) or not 0 < len(manifest[name]) <= 80 for name in versions):
        raise ValueError("The run is missing its recorded software versions.")

    saved = document.get("result")
    states = list(model.states)
    if not isinstance(saved, dict) or saved.get("states") != states:
        raise ValueError("The saved state order does not match the model.")
    if payload["operation"] == "compare":
        result = _verify_comparison(model, saved)
    else:
        plan = payload["plan"]
        audit = audit_plan(model, plan)
        if not _same_evidence(plan, saved.get("plan")) or not _same_evidence(audit, saved.get("audit")):
            raise ValueError("The saved audit does not match the supplied plan.")
        result = {"states": states, "plan": plan, "audit": audit}

    recorded = {name: manifest[name] for name in ("input_sha256", *versions)}
    return {"schema": RUN_SCHEMA, "input": payload, "result": result, "manifest": recorded}
