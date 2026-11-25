import numpy as np

from .model import AUDIT_TOLERANCE, marginal, probability_array

PAIRS = ((0, 0), (0, 1), (1, 0), (1, 1))


def describe_context(model, nodes, context):
    return {model.nodes[i]: list(PAIRS[value]) for i, value in zip(nodes, context)}


def audit_plan(model, candidate):
    """Check Prop. 4.7 for a supplied coupling and report failed conditionals."""
    width = model.width
    size = 2**width
    plan = probability_array(candidate, (size, size), "coupling")

    failures = []
    for side, observed, required in (
        ("source", plan.sum(axis=1), model.source), ("target", plan.sum(axis=0), model.target)
    ):
        error = float(np.max(np.abs(observed - required)))
        if error > AUDIT_TOLERANCE:
            failures.append({"kind": "joint_marginal", "side": side, "max_absolute_error": error})

    # Interleave X and Y axes so each coordinate represents (X_i, Y_i).
    interleaved = tuple(axis for i in range(width) for axis in (i, width + i))
    paired = plan.reshape((2,) * (2 * width)).transpose(interleaved).reshape((4,) * width)
    for node, parents in enumerate(model.parents):
        family = marginal(paired, (*parents, node))
        history = marginal(paired, tuple(range(node + 1)))

        def compare(kind, context, observed, required, **extra):
            error = float(np.max(np.abs(observed - required)))
            if error > AUDIT_TOLERANCE:
                failures.append({
                    "kind": kind,
                    "node": model.nodes[node],
                    "parents": describe_context(model, parents, context),
                    "observed": observed.tolist(),
                    "required": required.tolist(),
                    "max_absolute_error": error,
                    **extra,
                })

        for context in np.ndindex((4,) * len(parents)):
            mass = family[context].sum()
            if mass == 0:
                continue
            local = family[context].reshape(2, 2) / mass
            for side, axis, name in ((0, 1, "source"), (1, 0, "target")):
                parent_bits = tuple(PAIRS[z][side] for z in context)
                compare(
                    "conditional_marginal", context, local.sum(axis=axis),
                    model.laws[side][node][parent_bits], side=name, context_mass=float(mass),
                )

        if parents == tuple(range(node)):
            continue
        for prefix in np.ndindex((4,) * node):
            mass = history[prefix].sum()
            if mass == 0:
                continue
            context = tuple(prefix[i] for i in parents)
            row = family[context]
            compare(
                "history_dependence", context, history[prefix] / mass, row / row.sum(),
                history=describe_context(model, range(node), prefix), context_mass=float(mass),
            )

    return {
        "admissible": not failures,
        "absolute_tolerance": AUDIT_TOLERANCE,
        "bit_outcome_order": [0, 1],
        "pair_outcome_order": [list(pair) for pair in PAIRS],
        "failures": failures,
    }
