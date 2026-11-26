# Runtime and memory benchmarks

Run from the repository root with Python 3.10 or newer.

```sh
python -m pip install .
python -m benchmarks.measure --samples 15
```

The benchmark uses seed 358 to sample conditional probabilities from 0.25, 0.50, and 0.75 and builds two full-support laws compatible with each graph. The objective is Hamming cost. A comparison times both solvers, coupling reconstruction, and both audits, with the model already validated. The edge search starts with a raw model on the empty four-node graph and includes validation, every edge subset, and assembly of the report. The script performs a warm-up, measures each repetition with a wall clock, then measures peak allocations in a separate invocation with `tracemalloc`. Traced allocations cover part of process memory. Imports, the browser, and allocations outside Python's tracing are outside the measurement.

## Recorded baseline

Linux x86-64 container on an AMD EPYC 9V74 host, Python 3.12.14, NumPy 2.3.5, and NetworkX 3.7. Times are from 15 repetitions per workload.

| Workload | Coupling cells per graph | Graphs evaluated | Median (ms) | Min–max (ms) | Peak traced (KiB) |
|---|---:|---:|---:|---:|---:|
| Chain, 1 node | 4 | 1 | 0.36 | 0.30–0.49 | 9.9 |
| Chain, 2 nodes | 16 | 1 | 0.63 | 0.55–0.82 | 18.2 |
| Chain, 3 nodes | 64 | 1 | 1.25 | 1.16–1.50 | 42.9 |
| Chain, 4 nodes | 256 | 1 | 3.13 | 3.00–3.68 | 141.8 |
| Complete, 4 nodes | 256 | 1 | 4.05 | 3.84–4.62 | 146.7 |
| Collider, 3 nodes | 64 | 1 | 1.37 | 1.27–1.62 | 48.9 |
| Internal collider, 4 nodes | 256 | 1 | 8.92 | 8.67–9.69 | 148.6 |
| Exhaustive edge search, 4 nodes | 256 | 64 | 366.80 | 348.07–395.76 | 879.3 |

The dense witness has four times as many entries with each additional binary node. Four-node comparisons with the same matrix size span roughly 3–9 ms in this sample. The internal collider puts endpoint enumeration upstream of a descendant, while the three-node collider can minimize its final-node cost locally. Each graph also has different fitted laws, so this measures representative workloads. Exhaustive edge search evaluates all 64 subsets of the six possible forward edges. The measurements cover the supported sizes and are machine-dependent wall times. See [the technical note](../docs/technical-note.md) for the complexity limits.
