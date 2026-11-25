"""Independent full-coupling optimizers for well-conditioned binary test cases."""

from itertools import product

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import csr_matrix


def _family_index(state, family):
    return int("".join(str(state[node]) for node in family), 2)


def _full_costs(specification, states, parents):
    factors = specification.get("cost_factors", {})
    tables = []
    for node, name in enumerate(specification["nodes"]):
        if name in factors:
            family = (*parents[node], node)
            indices = [_family_index(state, family) for state in states]
            tables.append(np.asarray(factors[name])[np.ix_(indices, indices)])
        else:
            bits = states[:, node]
            tables.append(bits[:, None] != bits[None, :])
    return np.asarray(tables)


def _event(states, axes, bits):
    return (states[:, axes] == bits).all(axis=1)


def _conditional_zeros(states, law, node, parents):
    rows = {}
    for context in product((0, 1), repeat=len(parents)):
        mask = _event(states, parents, context)
        mass = sum(law[mask])
        zero_mass = sum(law[mask & (states[:, node] == 0)])
        rows[context] = (mass, zero_mass / mass if mass else 0.5)
    return rows


def _conditional_constraints(states, parents, source, target):
    """Return full-history marginal equations and optional paired-context disjunctions."""
    left = np.repeat(states, len(states), axis=0)
    right = np.tile(states, (len(states), 1))
    equations, switches = [], []
    for node, past in enumerate(parents):
        source_rows = _conditional_zeros(states, source, node, past)
        target_rows = _conditional_zeros(states, target, node, past)
        prefix = tuple(range(node))
        histories = tuple(product((0, 1), repeat=node))
        for x, y in product(histories, repeat=2):
            source_context = tuple(x[i] for i in past)
            target_context = tuple(y[i] for i in past)
            history = _event(left, prefix, x) & _event(right, prefix, y)
            equations.append(history * ((left[:, node] == 0) - source_rows[source_context][1]))
            equations.append(history * ((right[:, node] == 0) - target_rows[target_context][1]))

        if past == prefix:
            continue
        for (x, (source_mass, p)), (y, (target_mass, q)) in product(source_rows.items(), target_rows.items()):
            if min(source_mass, target_mass) == 0 or p in (0, 1) or q in (0, 1):
                continue
            context = _event(left, past, x) & _event(right, past, y)
            # A 2x2 endpoint has a zero on the diagonal or off it. For each pair of
            # cells, choose one whose row and column probabilities sum to at most one.
            diagonal_bit = int(p + q > 1)
            off_diagonal_bit = int(p > q)
            diagonal = context & (left[:, node] == diagonal_bit) & (right[:, node] == diagonal_bit)
            off_diagonal = context & (left[:, node] == off_diagonal_bit) & (right[:, node] != off_diagonal_bit)
            switches.append((diagonal, off_diagonal, min(source_mass, target_mass)))
    return np.asarray(equations), switches


def _constrained_cost(costs, marginals, probabilities, equations, switches):
    # One switch makes the same cell zero throughout each paired parent context.
    # The prescribed marginals then determine a unique 2x2 kernel for each history.
    cells, binary = len(costs), len(switches)
    equalities = np.vstack((marginals, equations))
    equalities = csr_matrix(np.pad(equalities, ((0, 0), (0, binary))))
    rhs = np.r_[probabilities, np.zeros(len(equations))]
    constraints = [LinearConstraint(equalities, rhs, rhs)]
    if switches:
        support = np.zeros((2 * binary, cells + binary))
        upper = np.zeros(2 * binary)
        for index, (diagonal, off_diagonal, mass) in enumerate(switches):
            support[2 * index : 2 * index + 2, :cells] = diagonal, off_diagonal
            support[2 * index : 2 * index + 2, cells + index] = mass, -mass
            upper[2 * index] = mass
        constraints.append(LinearConstraint(csr_matrix(support), -np.inf, upper))

    result = milp(
        np.r_[costs, np.zeros(binary)], integrality=np.r_[np.zeros(cells), np.ones(binary)],
        bounds=Bounds(0, 1), constraints=constraints, options={"mip_rel_gap": 0.0, "time_limit": 15},
    )
    if not result.success:
        raise AssertionError(f"Reference MILP did not reach an optimum: {result.message}")
    return result.fun


def reference_optima(specification):
    """Solve a classical LP and a graph-bicausal MILP with the full coupling as variables."""
    nodes = specification["nodes"]
    parents = [tuple(sorted(nodes.index(name) for name in specification["parents"][node])) for node in nodes]
    states = np.asarray(list(product((0, 1), repeat=len(nodes))))
    size = len(states)
    source = np.asarray(specification["source"])
    target = np.asarray(specification["target"])
    local_costs = _full_costs(specification, states, parents)
    costs = local_costs.sum(axis=0).ravel()
    marginals = np.vstack((np.repeat(np.eye(size), size, axis=1), np.tile(np.eye(size), size)))
    probabilities = np.r_[source, target]
    ordinary = linprog(costs, A_eq=csr_matrix(marginals), b_eq=probabilities, method="highs")
    if not ordinary.success:
        raise AssertionError(f"Reference LP did not reach an optimum: {ordinary.message}")

    equations, switches = _conditional_constraints(states, parents, source, target)
    constrained = _constrained_cost(costs, marginals, probabilities, equations, switches)
    return ordinary.fun, constrained, local_costs
