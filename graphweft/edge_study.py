from itertools import combinations, product

import numpy as np

from .audit import audit_plan
from .experiments import audit_matches, create_run, verify_run
from .model import Model
from .transport import costs_match

EDGE_SEARCH_SCHEMA = "graphweft.edge-search/1"


def compare_added_edge(specification, parent, child):
    """Add a forward edge while holding both laws and the full objective fixed."""
    model = Model.from_dict(specification)
    if parent not in model.nodes or child not in model.nodes:
        raise ValueError("Choose two node names from the model.")
    parent_index, child_index = model.nodes.index(parent), model.nodes.index(child)
    if parent_index >= child_index:
        raise ValueError("The parent must appear before the child in the model's node order.")
    if parent_index in model.parents[child_index]:
        raise ValueError("The model already contains that edge.")

    original = create_run({"operation": "compare", "model": specification})
    return {"original": original, **_compare_edge(model, original, parent_index, child_index)}


def scan_added_edges(specification):
    """Rank every missing forward edge, each added on its own to the original graph."""
    model = Model.from_dict(specification)
    original = create_run({"operation": "compare", "model": specification})
    studies = [
        _compare_edge(model, original, parent, child)
        for parent, child in _missing_edges(model)
    ]
    studies.sort(key=lambda study: study["cost_decrease"], reverse=True)
    return {"original": original, "edges": studies}


def search_added_edges(specification):
    """Find a minimum-cost expansion for each exact number of added forward edges."""
    model = Model.from_dict(specification)
    original = create_run({"operation": "compare", "model": specification})
    candidates = tuple(_missing_edges(model))
    baseline = original["result"]["constrained"]["cost"]
    ordinary = original["result"]["ordinary"]["cost"]
    minimum_edges = 0 if costs_match(model, ordinary, baseline) else None
    previous_cost = baseline
    best_by_count = []
    for count in range(1, len(candidates) + 1):
        added, best = min(
            ((edges, _evaluate_edges(model, original, edges)) for edges in combinations(candidates, count)),
            key=lambda entry: entry[1]["expanded"]["result"]["constrained"]["cost"],
        )
        plan = best["expanded"]["result"]["constrained"]
        cost = plan["cost"]
        if cost > previous_cost and not costs_match(model, previous_cost, cost):
            raise RuntimeError("The best constrained cost increased with more available edges")
        if minimum_edges is None and costs_match(model, ordinary, cost):
            minimum_edges = count
        best_by_count.append({
            "added_edges": [[model.nodes[parent], model.nodes[child]] for parent, child in added],
            **best,
            "original_graph_audit": audit_plan(model, plan["plan"]),
        })
        previous_cost = cost
    return {
        "schema": EDGE_SEARCH_SCHEMA,
        "original": original,
        "graphs_evaluated": 2 ** len(candidates),
        "minimum_edges_to_ordinary": minimum_edges,
        "best_additions": best_by_count,
    }


def verify_edge_search(document):
    """Recompute the search and check each saved witness, including tied alternatives."""
    if not isinstance(document, dict) or document.get("schema") != EDGE_SEARCH_SCHEMA:
        raise ValueError("This file does not use the supported GraphWeft edge search format.")
    original = verify_run(document.get("original"))
    if original["input"]["operation"] != "compare":
        raise ValueError("An edge search requires an original transport comparison.")
    specification = original["input"]["model"]
    model = Model.from_dict(specification)
    candidates = {(model.nodes[parent], model.nodes[child]): (parent, child) for parent, child in _missing_edges(model)}
    saved = document.get("best_additions")
    if not isinstance(saved, list) or len(saved) != len(candidates):
        raise ValueError("The edge search needs one result per number of added edges.")

    reference = search_added_edges(specification)
    for key in ("graphs_evaluated", "minimum_edges_to_ordinary"):
        expected = reference[key]
        claimed = document.get(key)
        if key not in document or type(claimed) is not type(expected) or claimed != expected:
            raise ValueError(f"The saved edge search has an incorrect {key.replace('_', ' ')}.")

    verified = []
    for count, (study, best) in enumerate(zip(saved, reference["best_additions"]), 1):
        if not isinstance(study, dict):
            raise ValueError(f"The saved result for {count} added edges must be an object.")
        added = study.get("added_edges")
        if (not isinstance(added, list) or len(added) != count or any(
            not isinstance(edge, list) or len(edge) != 2 or any(not isinstance(node, str) for node in edge)
            for edge in added
        )):
            raise ValueError(f"The saved result must list {count} added edges.")
        edges = [tuple(edge) for edge in added]
        if len(set(edges)) != count or any(edge not in candidates for edge in edges):
            raise ValueError("The saved additions must be distinct missing forward edges.")

        expanded = verify_run(study.get("expanded"))
        expected = _expanded_specification(model, specification, [candidates[edge] for edge in edges])
        if expanded["input"] != {"operation": "compare", "model": expected}:
            raise ValueError("The saved expanded model must preserve the original laws and costs and add the listed edges.")
        plan = expanded["result"]["constrained"]
        optimum = best["expanded"]["result"]["constrained"]["cost"]
        if not costs_match(model, optimum, plan["cost"]):
            raise ValueError(f"The saved combination of {count} added edges does not attain the best cost.")
        decrease = _cost_decrease(model, original["result"]["constrained"]["cost"], plan["cost"])
        if decrease < 0 or not costs_match(model, decrease, study.get("cost_decrease")):
            raise ValueError("The saved cost decrease does not agree with the two verified plans.")
        audit = audit_plan(model, plan["plan"])
        if not audit_matches(audit, study.get("original_graph_audit")):
            raise ValueError("The saved original-graph audit does not match the expanded plan.")
        verified.append({"added_edges": added, "expanded": expanded, "cost_decrease": decrease, "original_graph_audit": audit})

    return {**reference, "original": original, "best_additions": verified}


def _missing_edges(model):
    return (
        (parent, child)
        for child, parents in enumerate(model.parents)
        for parent in range(child)
        if parent not in parents
    )


def _compare_edge(model, original, parent_index, child_index):
    study = _evaluate_edges(model, original, ((parent_index, child_index),))
    plan = study["expanded"]["result"]["constrained"]["plan"]
    return {
        "edge": [model.nodes[parent_index], model.nodes[child_index]],
        **study,
        "original_graph_audit": audit_plan(model, plan),
    }


def _evaluate_edges(model, original, added):
    specification = _expanded_specification(model, original["input"]["model"], added)
    expanded = create_run({"operation": "compare", "model": specification})
    before = original["result"]
    after = expanded["result"]
    if not costs_match(model, before["ordinary"]["cost"], after["ordinary"]["cost"]):
        raise RuntimeError("Adding edges changed the ordinary optimum despite fixed laws and costs")
    decrease = _cost_decrease(model, before["constrained"]["cost"], after["constrained"]["cost"])
    if decrease < 0:
        raise RuntimeError("Adding edges increased the constrained optimum despite fixed laws and costs")
    return {"expanded": expanded, "cost_decrease": decrease}


def _cost_decrease(model, before, after):
    return 0.0 if costs_match(model, before, after) else before - after


def _expanded_specification(model, canonical, added):
    expanded_parents = [list(parents) for parents in model.parents]
    for parent, child in added:
        expanded_parents[child].append(parent)
    for parents in expanded_parents:
        parents.sort()
    expanded_specification = {
        **canonical,
        "parents": {
            node: [model.nodes[parent] for parent in parents]
            for node, parents in zip(model.nodes, expanded_parents)
        },
    }
    if model.cost_factors:
        factors = dict(canonical["cost_factors"])
        for child in sorted({child for _, child in added}):
            node = model.nodes[child]
            if node in model.cost_factors:
                factors[node] = _lift_cost_table(model.cost_factors[node], model.parents[child], expanded_parents[child])
        expanded_specification["cost_factors"] = factors
    return expanded_specification


def _lift_cost_table(table, old_parents, new_parents):
    # Project each new family state onto the old parent bits and the child's bit.
    positions = tuple(new_parents.index(parent) for parent in old_parents) + (len(new_parents),)
    old_states = {bits: index for index, bits in enumerate(product((0, 1), repeat=len(positions)))}
    indices = [
        old_states[tuple(bits[position] for position in positions)]
        for bits in product((0, 1), repeat=len(new_parents) + 1)
    ]
    return table[np.ix_(indices, indices)].tolist()
