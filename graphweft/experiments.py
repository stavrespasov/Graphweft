import hashlib
import json
import math
import platform

import networkx as nx
import numpy as np

from .audit import audit_plan
from .model import AUDIT_TOLERANCE, Model, probability_array
from .transport import compare, cost_matrices, costs_match, plan_costs

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
    if model.cost_factors:
        payload["model"]["cost_factors"] = {name: (table + 0.0).tolist() for name, table in model.cost_factors.items()}
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
        "networkx": nx.__version__,
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


def audit_matches(audit, claimed, legacy=False):
    if legacy and isinstance(claimed, dict) and isinstance(claimed.get("failures"), list):
        recorded = claimed["failures"]
        if len(recorded) == len(audit["failures"]) and all(isinstance(failure, dict) for failure in recorded):
            # Legacy findings predate the per-state marginal diagnostics.
            state_diagnostics = {"missing_states", "unexpected_states", "misweighted_states"}
            audit = {**audit, "failures": [
                {key: value for key, value in finding.items()
                 if key not in state_diagnostics or key in saved}
                for finding, saved in zip(audit["failures"], recorded)
            ]}
    return _same_evidence(audit, claimed)


def _verify_comparison(model, saved, legacy):
    reference = compare(model)
    matrices = cost_matrices(model)
    result = {"states": list(model.states)}
    for name in ("ordinary", "constrained"):
        claim = saved.get(name)
        if not isinstance(claim, dict):
            raise ValueError(f"The saved run is missing its {name} plan.")
        plan = probability_array(claim.get("plan"), matrices[0].shape, f"{name} coupling")
        audit = audit_plan(model, plan)
        marginal_failure = any(failure["kind"] == "joint_marginal" for failure in audit["failures"])
        if marginal_failure or (name == "constrained" and not audit["admissible"]):
            raise ValueError(f"The saved {name} plan fails its feasibility checks.")
        by_node = plan_costs(model, plan, matrices)
        cost = sum(by_node.values())
        if not costs_match(model, cost, claim.get("cost")):
            raise ValueError(f"The saved {name} cost does not match its plan.")
        if not costs_match(model, reference[name]["cost"], cost):
            raise ValueError(f"The saved {name} cost does not match the recomputed optimum.")
        if "cost_by_node" in claim:
            recorded = claim["cost_by_node"]
            if not isinstance(recorded, dict) or recorded.keys() != by_node.keys() or any(
                not costs_match(model, value, recorded[node]) for node, value in by_node.items()
            ):
                raise ValueError(f"The saved {name} cost breakdown does not match its plan.")
        if not audit_matches(audit, claim.get("audit"), legacy):
            raise ValueError(f"The saved {name} audit does not match its plan.")
        result[name] = {"plan": plan.tolist(), "cost": cost, "cost_by_node": by_node, "audit": audit}

    gap = result["constrained"]["cost"] - result["ordinary"]["cost"]
    if not costs_match(model, gap, saved.get("cost_gap")):
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
    solver_library = "networkx" if "networkx" in manifest else "scipy"
    legacy = solver_library == "scipy"
    versions = ("python", "numpy", solver_library)
    if any(not isinstance(manifest.get(name), str) or not 0 < len(manifest[name]) <= 80 for name in versions):
        raise ValueError("The run is missing its recorded software versions.")

    saved = document.get("result")
    states = list(model.states)
    if not isinstance(saved, dict) or saved.get("states") != states:
        raise ValueError("The saved state order does not match the model.")
    if payload["operation"] == "compare":
        result = _verify_comparison(model, saved, legacy)
    else:
        plan = payload["plan"]
        audit = audit_plan(model, plan)
        if not _same_evidence(plan, saved.get("plan")) or not audit_matches(audit, saved.get("audit"), legacy):
            raise ValueError("The saved audit does not match the supplied plan.")
        result = {"states": states, "plan": plan, "audit": audit}

    recorded = {name: manifest[name] for name in ("input_sha256", *versions)}
    return {"schema": RUN_SCHEMA, "input": payload, "result": result, "manifest": recorded}


def verify_saved_document(document):
    # An edge search contains ordinary run documents and uses their verifier.
    from .edge_study import EDGE_SEARCH_SCHEMA, verify_edge_search

    if isinstance(document, dict) and document.get("schema") == EDGE_SEARCH_SCHEMA:
        return verify_edge_search(document)
    return verify_run(document)
