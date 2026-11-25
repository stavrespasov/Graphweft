from dataclasses import dataclass

import numpy as np

INPUT_TOLERANCE = 1e-10
AUDIT_TOLERANCE = 1e-8


def marginal(tensor, nodes):
    omitted = tuple(i for i in range(tensor.ndim) if i not in nodes)
    return tensor.sum(axis=omitted)


def probability_array(raw, shape, name):
    try:
        array = np.asarray(raw)
        if array.shape != shape or array.dtype.kind not in "iuf":
            raise ValueError
        array = array.astype(np.float64)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be a numeric array with shape {shape}") from None
    if not np.all(np.isfinite(array)) or np.any(array < 0) or np.any(array > 1 + INPUT_TOLERANCE):
        raise ValueError(f"{name} must have finite, nonnegative entries bounded by one")
    return array


def local_kernels(law, parents):
    kernels = []
    for node, past in enumerate(parents):
        family = marginal(law, (*past, node))
        mass = family.sum(axis=-1, keepdims=True)
        # A parent event of zero probability leaves its kernel unspecified.
        kernels.append(np.divide(family, mass, out=np.full_like(family, 0.5), where=mass > 0))
    return tuple(kernels)


@dataclass(frozen=True, eq=False)
class Model:
    nodes: tuple
    parents: tuple
    source: np.ndarray
    target: np.ndarray
    laws: tuple

    @property
    def width(self):
        return len(self.nodes)

    @property
    def states(self):
        return tuple(format(state, f"0{self.width}b") for state in range(2**self.width))

    @classmethod
    def from_dict(cls, specification):
        if not isinstance(specification, dict):
            raise ValueError("Model must be a JSON object")

        nodes = specification.get("nodes")
        if (not isinstance(nodes, list) or not 1 <= len(nodes) <= 4 or
                any(not isinstance(node, str) or not node.strip() for node in nodes) or
                len(set(nodes)) != len(nodes)):
            raise ValueError("Provide one to four distinct node names in topological order")

        assignments = specification.get("parents")
        if not isinstance(assignments, dict) or set(assignments) != set(nodes):
            raise ValueError("Provide a parents list for every node")
        node_index = {node: index for index, node in enumerate(nodes)}
        parents = []
        for index, node in enumerate(nodes):
            names = assignments[node]
            if (not isinstance(names, list) or
                    any(not isinstance(name, str) or name not in nodes[:index] for name in names) or
                    len(set(names)) != len(names)):
                raise ValueError(f"Parents of {node} must be distinct nodes appearing before it")
            parents.append(tuple(sorted(node_index[name] for name in names)))

        distributions = []
        laws = []
        for side in ("source", "target"):
            vector = probability_array(specification.get(side), (2**len(nodes),), side)
            total = vector.sum()
            if abs(total - 1) > INPUT_TOLERANCE:
                raise ValueError(f"{side} probabilities must sum to one")
            vector /= total
            law = vector.reshape((2,) * len(nodes))
            kernels = local_kernels(law, parents)
            for state in np.ndindex(law.shape):
                reconstructed = float(np.prod([
                    kernels[i][tuple(state[parent] for parent in past) + (state[i],)]
                    for i, past in enumerate(parents)
                ]))
                if not np.isclose(reconstructed, law[state], rtol=1e-8, atol=INPUT_TOLERANCE):
                    raise ValueError(f"{side} is incompatible with the supplied DAG")
            vector.setflags(write=False)
            distributions.append(vector)
            laws.append(kernels)
        return cls(tuple(nodes), tuple(parents), *distributions, tuple(laws))
