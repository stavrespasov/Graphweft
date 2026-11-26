from itertools import combinations, product

import numpy as np

from .audit import audit_plan
from .experiments import create_run
from .model import Model
from .transport import costs_match


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
        "original": original,
        "graphs_evaluated": 2 ** len(candidates),
        "minimum_edges_to_ordinary": minimum_edges,
        "best_additions": best_by_count,
    }


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
    canonical = original["input"]["model"]
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

    expanded = create_run({"operation": "compare", "model": expanded_specification})
    before = original["result"]
    after = expanded["result"]
    if not costs_match(model, before["ordinary"]["cost"], after["ordinary"]["cost"]):
        raise RuntimeError("Adding edges changed the ordinary optimum despite fixed laws and costs")
    before_cost = before["constrained"]["cost"]
    after_cost = after["constrained"]["cost"]
    decrease = 0.0 if costs_match(model, before_cost, after_cost) else before_cost - after_cost
    if decrease < 0:
        raise RuntimeError("Adding edges increased the constrained optimum despite fixed laws and costs")
    return {"expanded": expanded, "cost_decrease": decrease}


def _lift_cost_table(table, old_parents, new_parents):
    # Project each new family state onto the old parent bits and the child's bit.
    positions = tuple(new_parents.index(parent) for parent in old_parents) + (len(new_parents),)
    old_states = {bits: index for index, bits in enumerate(product((0, 1), repeat=len(positions)))}
    indices = [
        old_states[tuple(bits[position] for position in positions)]
        for bits in product((0, 1), repeat=len(new_parents) + 1)
    ]
    return table[np.ix_(indices, indices)].tolist()
