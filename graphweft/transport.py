from math import prod

import numpy as np
from scipy.optimize import linprog

from .audit import PAIRS, audit_plan
from .model import AUDIT_TOLERANCE

_HAMMING_PAIR = np.array([int(x != y) for x, y in PAIRS])


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


def _graph(model):
    parents = model.parents
    for node, past in enumerate(parents):
        if past and not set(past[:-1]).issubset(parents[past[-1]]):
            raise ValueError(f"Graph solver requires a perfect DAG. Parents of {model.nodes[node]} are not a clique")

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
        objective[indices[node]] = _HAMMING_PAIR
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

            distributions = tuple(
                model.laws[side][node][tuple(PAIRS[z][side] for z in context)]
                for side in (0, 1)
            )
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

    dimension = len(model.source)
    plan = np.zeros((dimension, dimension))
    for outcome in np.ndindex((4,) * model.width):
        weight = prod(
            kernels[i][tuple(outcome[j] for j in pa) + (outcome[i],)]
            for i, pa in enumerate(parents)
        )
        left = int("".join(str(PAIRS[z][0]) for z in outcome), 2)
        right = int("".join(str(PAIRS[z][1]) for z in outcome), 2)
        plan[left, right] = weight
    return plan, float(optimum.fun)


def compare(model):
    bits = np.array([list(state) for state in model.states])
    costs = (bits[:, None, :] != bits[None, :, :]).sum(axis=-1)
    constrained = _graph(model)
    ordinary = _ordinary(model, costs)
    result = {"states": list(model.states)}
    for name, (plan, optimum) in (("ordinary", ordinary), ("constrained", constrained)):
        cost = float((plan * costs).sum())
        if abs(cost - optimum) > AUDIT_TOLERANCE:
            raise RuntimeError(f"Reconstructed {name} witness disagrees with the LP objective")
        audit = audit_plan(model, plan)
        if (name == "constrained" and not audit["admissible"]) or any(
            failure["kind"] == "joint_marginal" for failure in audit["failures"]
        ):
            raise RuntimeError(f"The returned {name} witness failed its feasibility audit")
        result[name] = {"cost": cost, "plan": plan.tolist(), "audit": audit}

    gap = result["constrained"]["cost"] - result["ordinary"]["cost"]
    if gap < -AUDIT_TOLERANCE:
        raise RuntimeError("Constrained optimum undercuts the ordinary optimum")
    result["cost_gap"] = gap
    return result
