from itertools import product
from math import isclose, isfinite, prod

import numpy as np
from scipy.optimize import linprog

from .audit import PAIRS, audit_plan
from .model import AUDIT_TOLERANCE, paired_tensor

_HAMMING_PAIR = np.array([int(x != y) for x, y in PAIRS])
_COLLIDER = ((), (), (0, 1))


def _solve(objective, rows, targets):
    solution = linprog(
        objective, A_eq=rows, b_eq=targets, method="highs",
        options={"primal_feasibility_tolerance": 1e-9, "dual_feasibility_tolerance": 1e-9},
    )
    if not solution.success:
        raise RuntimeError(f"HiGHS failed with status {solution.status}: {solution.message}")
    residual = np.max(np.abs(np.asarray(rows) @ solution.x - targets))
    if residual > AUDIT_TOLERANCE:
        raise RuntimeError("HiGHS primal residual exceeds the audit tolerance")
    return solution


def _ordinary(model, costs):
    size = len(model.source)
    rows = []
    for state in range(size):
        row = np.zeros((size, size))
        row[state, :] = 1
        rows.append(row.ravel())
    for state in range(size):
        row = np.zeros((size, size))
        row[:, state] = 1
        rows.append(row.ravel())
    optimum = _solve(costs.ravel(), rows, np.r_[model.source, model.target])
    return optimum.x.reshape(size, size), float(optimum.fun)


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


def _graph(model):
    parents = model.parents
    for node, past in enumerate(parents):
        if past and not set(past[:-1]).issubset(parents[past[-1]]):
            raise ValueError(
                f"Graph solver supports perfect DAGs and the binary three-node collider. "
                f"Parents of {model.nodes[node]} are not a clique."
            )

    families = [(*past, node) for node, past in enumerate(parents)]
    indices = []
    size = 0
    for family in families:
        cells = 4**len(family)
        indices.append(np.arange(size, size + cells).reshape((4,) * len(family)))
        size += cells

    rows, targets = [], []
    objective = np.empty(size)
    fixed_marginals = []
    for node, past in enumerate(parents):
        node_marginals = {}
        objective[indices[node]] = _paired_costs(model, node)
        for context in np.ndindex((4,) * len(past)):
            entries = indices[node][context]
            equation = np.zeros(size)
            equation[entries] = 1
            if past:
                proximal = past[-1]
                previous = indices[proximal]
                positions = tuple(families[proximal].index(i) for i in past)
                for previous_context in np.ndindex(previous.shape):
                    if tuple(previous_context[i] for i in positions) == context:
                        equation[previous[previous_context]] -= 1
            rows.append(equation)
            targets.append(0 if past else 1)

            distributions = _conditional_marginals(model, node, context)
            node_marginals[context] = distributions
            for side, law in enumerate(distributions):
                for bit in (0, 1):
                    equation = np.zeros(size)
                    equation[entries] = [int(z[side] == bit) - law[bit] for z in PAIRS]
                    rows.append(equation)
                    targets.append(0)
        fixed_marginals.append(node_marginals)

    optimum = _solve(objective, rows, np.array(targets))
    kernels = []
    for node, past in enumerate(parents):
        kernel = np.empty(indices[node].shape)
        for context, (left, right) in fixed_marginals[node].items():
            weights = optimum.x[indices[node][context]]
            mass = weights.sum()
            kernel[context] = weights / mass if mass > 0 else np.outer(left, right).ravel()
        kernels.append(kernel)

    return _joint_from_kernels(model, kernels), float(optimum.fun)


def _binary_endpoints(left, right):
    # Fixing the (0, 0) mass determines the other three cells of a binary coupling.
    lower = max(0.0, left[0] - right[1])
    upper = min(left[0], right[0])
    return tuple(
        np.maximum((mass, left[0] - mass, right[0] - mass, left[1] - right[0] + mass), 0)
        for mass in (lower, upper)
    )


def _collider(model):
    child_cost = np.broadcast_to(_paired_costs(model, 2), (4, 4, 4))
    child_plan = np.empty(child_cost.shape)
    remaining_cost = np.empty((4, 4))
    for context in np.ndindex(4, 4):
        endpoints = np.array(_binary_endpoints(*_conditional_marginals(model, 2, context)))
        values = endpoints @ child_cost[context]
        chosen = np.argmin(values)
        child_plan[context] = endpoints[chosen]
        remaining_cost[context] = values[chosen]

    root_cost = _paired_costs(model, 0)[:, None] + _paired_costs(model, 1)[None, :]
    objective = root_cost + remaining_cost
    root_options = [_binary_endpoints(*_conditional_marginals(model, node, ())) for node in (0, 1)]
    # A bilinear objective on the two root intervals attains a minimum at a corner.
    value, roots = min(
        ((float(left @ objective @ right), (left, right)) for left, right in product(*root_options)),
        key=lambda candidate: candidate[0],
    )
    return _joint_from_kernels(model, (*roots, child_plan)), value


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
    constrained = _collider(model) if model.parents == _COLLIDER else _graph(model)
    ordinary = _ordinary(model, costs)
    result = {"states": list(model.states)}
    for name, (plan, optimum) in (("ordinary", ordinary), ("constrained", constrained)):
        cost = float((plan * costs).sum())
        if abs(cost - optimum) > AUDIT_TOLERANCE:
            raise RuntimeError(f"Reconstructed {name} witness disagrees with the LP objective")
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
