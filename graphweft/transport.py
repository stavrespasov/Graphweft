from itertools import product
from math import isclose, isfinite, lcm, prod

import networkx as nx
import numpy as np

from .audit import PAIRS, audit_plan
from .model import AUDIT_TOLERANCE, paired_tensor

_HAMMING_PAIR = np.array([int(x != y) for x, y in PAIRS])


def _integer_units(values):
    # Every finite float is a dyadic rational, so the largest denominator is a common one.
    ratios = [float(value).as_integer_ratio() for value in values]
    scale = max(denominator for _, denominator in ratios)
    return [numerator * (scale // denominator) for numerator, denominator in ratios], scale


def _ordinary(model, costs):
    # Normalize the two integer measures separately to the same total supply and demand.
    source, _ = _integer_units(model.source)
    target, _ = _integer_units(model.target)
    source_total, target_total = sum(source), sum(target)
    total = lcm(source_total, target_total)
    supply = {i: mass * (total // source_total) for i, mass in enumerate(source) if mass > 0}
    demand = {j: mass * (total // target_total) for j, mass in enumerate(target) if mass > 0}
    weights, cost_scale = _integer_units(costs.ravel())
    size = len(source)

    graph = nx.DiGraph()
    graph.add_nodes_from((i, {"demand": -mass}) for i, mass in supply.items())
    graph.add_nodes_from((size + j, {"demand": mass}) for j, mass in demand.items())
    graph.add_weighted_edges_from(
        (i, size + j, weights[size * i + j]) for i in supply for j in demand
    )
    optimum, flows = nx.network_simplex(graph)
    plan = np.zeros_like(costs)
    for i in supply:
        for destination, mass in flows[i].items():
            plan[i, destination - size] = mass / total
    return plan, optimum / (total * cost_scale)


def _paired_costs(model, node):
    factor = model.cost_factors.get(model.nodes[node])
    if factor is None:
        return _HAMMING_PAIR / model.cost_scale
    return paired_tensor(factor / model.cost_scale, len(model.parents[node]) + 1)


def _conditional_marginals(model, node, context):
    return tuple(
        model.laws[side][node][tuple(PAIRS[z][side] for z in context)]
        for side in (0, 1)
    )


def _joint_from_kernels(model, kernels):
    dimension = len(model.source)
    plan = np.zeros((dimension, dimension))
    for outcome in np.ndindex((4,) * model.width):
        weight = prod(
            kernels[i][tuple(outcome[j] for j in pa) + (outcome[i],)]
            for i, pa in enumerate(model.parents)
        )
        left = int("".join(str(PAIRS[z][0]) for z in outcome), 2)
        right = int("".join(str(PAIRS[z][1]) for z in outcome), 2)
        plan[left, right] = weight
    return plan


def _perfect_graph(model):
    """Eliminate nodes in reverse order using the perfect-DAG backward recurrence."""
    families = [(*parents, node) for node, parents in enumerate(model.parents)]
    costs = [
        np.broadcast_to(_paired_costs(model, node), (4,) * len(family)).copy()
        for node, family in enumerate(families)
    ]
    kernels = [np.empty_like(cost) for cost in costs]
    optimum = 0.0
    for node in reversed(range(model.width)):
        parents = model.parents[node]
        remaining = np.empty((4,) * len(parents))
        for context in np.ndindex(remaining.shape):
            endpoints = np.array(_binary_endpoints(*_conditional_marginals(model, node, context)))
            values = endpoints @ costs[node][context]
            choice = values.argmin()
            kernels[node][context] = endpoints[choice]
            remaining[context] = values[choice]

        if parents:
            # A clique of parents fits into the family of the last parent in node order.
            proximal = parents[-1]
            shape = tuple(4 if axis in parents else 1 for axis in families[proximal])
            costs[proximal] += remaining.reshape(shape)
        else:
            optimum += float(remaining)
    return _joint_from_kernels(model, kernels), optimum


def _binary_endpoints(left, right):
    # Each endpoint has at least one exact zero, including when a marginal is deterministic.
    x0, x1 = left
    y0, y1 = right
    # Use the smaller operands when subtracting complementary probabilities.
    lower = x0 - y1 if max(x0, y1) <= max(x1, y0) else y0 - x1
    upper = x0 - y0 if max(x0, y0) <= max(x1, y1) else y1 - x1
    return (
        (max(0.0, lower), min(x0, y1), min(x1, y0), max(0.0, -lower)),
        (min(x0, y0), max(0.0, upper), max(0.0, -upper), min(x1, y1)),
    )


def _binary_graph(model):
    """Minimize a multi-affine objective over the binary coupling intervals."""
    history_contexts, endpoint_tables, endpoint_costs = [], [], []
    for node, parents in enumerate(model.parents):
        # For each paired history, index the row for its paired parent context.
        histories = np.indices((4,) * node).reshape(node, 4**node)
        contexts = np.zeros(4**node, dtype=int)
        for parent in parents:
            contexts = 4 * contexts + histories[parent]
        history_contexts.append(contexts)

        endpoints = np.array([
            _binary_endpoints(*_conditional_marginals(model, node, context))
            for context in np.ndindex((4,) * len(parents))
        ])
        costs = _paired_costs(model, node).reshape(-1, 4)
        endpoint_tables.append(endpoints)
        endpoint_costs.append((endpoints * costs[:, None, :]).sum(axis=-1))

    # The last node has no descendants. Choose the cheaper endpoint for each parent context.
    last = model.width - 1
    last_rows = np.arange(len(endpoint_tables[last]))
    last_choices = endpoint_costs[last].argmin(axis=1)
    last_kernel = endpoint_tables[last][last_rows, last_choices]
    last_cost_by_history = endpoint_costs[last][last_rows, last_choices][history_contexts[last]]

    def search(node, history_mass):
        if node == last:
            return float(history_mass @ last_cost_by_history), (last_kernel,)

        endpoints = endpoint_tables[node]
        contexts = history_contexts[node]
        rows = np.arange(len(endpoints))
        context_mass = np.bincount(contexts, weights=history_mass, minlength=len(endpoints))
        distinct = (endpoints[:, 0] != endpoints[:, 1]).any(axis=1)
        active = np.flatnonzero((context_mass > 0) & distinct)
        choices = np.zeros(len(endpoints), dtype=int)
        best_value, best_kernels = float("inf"), ()
        for selected in product((0, 1), repeat=len(active)):
            choices[active] = selected
            kernel = endpoints[rows, choices]
            next_mass = (history_mass[:, None] * kernel[contexts]).ravel()
            future_cost, suffix = search(node + 1, next_mass)
            value = float(context_mass @ endpoint_costs[node][rows, choices]) + future_cost
            if value < best_value:
                best_value, best_kernels = value, (kernel, *suffix)
        return best_value, best_kernels

    value, rows = search(0, np.ones(1))
    kernels = tuple(
        table.reshape((4,) * (len(parents) + 1))
        for table, parents in zip(rows, model.parents)
    )
    return _joint_from_kernels(model, kernels), value


def hamming_costs(model):
    bits = np.array([list(state) for state in model.states])
    return (bits[:, None, :] != bits[None, :, :]).sum(axis=-1)


def cost_matrices(model):
    """Project each cost factor to the full coupling, in solver units."""
    bits = np.array([list(state) for state in model.states], dtype=int)
    matrices = []
    for node, parents in enumerate(model.parents):
        factor = model.cost_factors.get(model.nodes[node])
        if factor is None:
            matrix = bits[:, node, None] != bits[None, :, node]
        else:
            family = (*parents, node)
            weights = 2 ** np.arange(len(family) - 1, -1, -1)
            states = bits[:, family] @ weights
            matrix = factor[states[:, None], states[None, :]]
        matrices.append(matrix / model.cost_scale)
    return matrices


def plan_costs(model, plan, matrices):
    return {
        node: float((matrix * plan).sum()) * model.cost_scale
        for node, matrix in zip(model.nodes, matrices)
    }


def costs_match(model, expected, claimed):
    if type(claimed) not in (int, float):
        return False
    try:
        return isfinite(expected) and isfinite(claimed) and isclose(
            expected / model.cost_scale, claimed / model.cost_scale, abs_tol=AUDIT_TOLERANCE, rel_tol=0,
        )
    except OverflowError:
        return False


def compare(model):
    matrices = cost_matrices(model)
    costs = np.sum(matrices, axis=0)
    perfect = all(not past or set(past[:-1]).issubset(model.parents[past[-1]]) for past in model.parents)
    constrained = _perfect_graph(model) if perfect else _binary_graph(model)
    ordinary = _ordinary(model, costs)
    result = {"states": list(model.states)}
    for name, (plan, optimum) in (("ordinary", ordinary), ("constrained", constrained)):
        cost = float((plan * costs).sum())
        if abs(cost - optimum) > AUDIT_TOLERANCE:
            raise RuntimeError(f"Reconstructed {name} witness disagrees with the solver objective")
        by_node = plan_costs(model, plan, matrices)
        reported_cost = sum(by_node.values())
        if not isfinite(reported_cost):
            raise RuntimeError(f"The reconstructed {name} cost is outside the numeric range")
        audit = audit_plan(model, plan)
        if (name == "constrained" and not audit["admissible"]) or any(
            failure["kind"] == "joint_marginal" for failure in audit["failures"]
        ):
            raise RuntimeError(f"The returned {name} witness failed its feasibility audit")
        result[name] = {"cost": reported_cost, "cost_by_node": by_node, "plan": plan.tolist(), "audit": audit}

    gap = result["constrained"]["cost"] - result["ordinary"]["cost"]
    if gap / model.cost_scale < -AUDIT_TOLERANCE:
        raise RuntimeError("Constrained optimum undercuts the ordinary optimum")
    result["cost_gap"] = gap
    return result
