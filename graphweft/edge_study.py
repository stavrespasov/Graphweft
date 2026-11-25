from itertools import product

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
    old_parents = model.parents[child_index]
    if parent_index in old_parents:
        raise ValueError("The model already contains that edge.")

    original = create_run({"operation": "compare", "model": specification})
    canonical = original["input"]["model"]
    new_parents = sorted((*old_parents, parent_index))
    expanded_specification = {
        **canonical,
        "parents": {**canonical["parents"], child: [model.nodes[index] for index in new_parents]},
    }
    if child in model.cost_factors:
        # Dropping the extra parent bit maps each new family state to its original row or column.
        added_position = new_parents.index(parent_index)
        old_states = {bits: index for index, bits in enumerate(product((0, 1), repeat=len(old_parents) + 1))}
        indices = [
            old_states[bits[:added_position] + bits[added_position + 1:]]
            for bits in product((0, 1), repeat=len(new_parents) + 1)
        ]
        lifted = model.cost_factors[child][np.ix_(indices, indices)]
        expanded_specification["cost_factors"] = {**canonical["cost_factors"], child: lifted.tolist()}

    expanded = create_run({"operation": "compare", "model": expanded_specification})
    before = original["result"]
    after = expanded["result"]
    if not costs_match(model, before["ordinary"]["cost"], after["ordinary"]["cost"]):
        raise RuntimeError("Adding the edge changed the ordinary optimum despite fixed laws and costs")
    decrease = before["constrained"]["cost"] - after["constrained"]["cost"]
    if decrease < 0 and not costs_match(model, before["constrained"]["cost"], after["constrained"]["cost"]):
        raise RuntimeError("Adding the edge increased the constrained optimum despite fixed laws and costs")
    return {
        "edge": [parent, child],
        "original": original,
        "expanded": expanded,
        "cost_decrease": max(0.0, decrease),
        "original_graph_audit": audit_plan(model, after["constrained"]["plan"]),
    }
