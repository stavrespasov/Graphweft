# GraphWeft

GraphWeft compares ordinary optimal transport with **graph-bicausal optimal transport** on a supplied directed acyclic graph. It shows how an information constraint changes the lowest transport cost and pinpoints the conditional probabilities that make a plan inadmissible.

## Browser workbench

From the repository root, use Python 3.10 or newer in a virtual environment.

```sh
python -m pip install -e .
python -m graphweft serve
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The fork example opens with both coupling matrices on the same color scale. Select either plan in the audit panel to see the failed conditions or confirm the checks passed. Choose **Shared-coin audit** to compare the two conditional distributions at node C. Open **Edit inputs** to run your own model or supply a coupling matrix. The workbench uses the local Python solver.

## Save and verify a run

Select **Save run** after a comparison or audit. The JSON file contains the inputs, coupling matrices, costs where applicable, audit findings, an input checksum, and the Python, NumPy and SciPy versions. **Open run** checks that file with the current solver before displaying the saved plans. GraphWeft checks the saved plans and costs independently of which optimal coupling the solver happens to return on replay.

```sh
python -m graphweft verify-run path/to/saved-run.json
```

A verified audit can still report an inadmissible plan. For example, replay verifies that the shared-coin run correctly reports the dependence violation at node C. Run files are limited to 1 MiB.

## Command line

```sh
python -m graphweft compare examples/binary_chain.json --summary
```

The chain example takes equal mass on `00` and `11` to equal mass on `00` and `01`. Ordinary transport can match the second bit perfectly. That mapping also makes the target’s second bit reveal the source’s first bit. With the graph’s conditional constraints enforced, the minimum Hamming cost rises from **0.5 to 1.0**.

| Example | Ordinary OT | Graph-bicausal OT |
|---|---:|---:|
| [Two-node chain](examples/binary_chain.json) | 0.5 | 1.0 |
| [Three-node fork](examples/binary_fork.json) | 1.0 | 1.5 |

Use `python -m graphweft compare examples/binary_fork.json --summary` for the larger example. Omit `--summary` to see both coupling matrices and all audit findings.

## Audit a coupling

```sh
python -m graphweft audit examples/shared_coin_model.json examples/shared_coin_plan.json --summary
```

In this fork, node A is the parent of B and C. The supplied coupling uses one shared coin to flip both children. The auditor flags node C because its paired outcomes depend on B even after conditioning on A.

| Paired outcome at C | `00` | `01` | `10` | `11` |
|---|---:|---:|---:|---:|
| Given A and B are both `00` | 0.50 | 0.00 | 0.00 | 0.50 |
| Given A is `00` | 0.25 | 0.25 | 0.25 | 0.25 |

This example returns exit code `1` for an inadmissible plan and prints the failed condition. A passing audit returns `0`. An input or solver error returns `2`.

## Use your own model

Start from [the chain fixture](examples/binary_chain.json). Define one to four binary nodes in topological order and list the parents of each node. The source and target vectors assign mass to lexicographically ordered bit strings. For two nodes, the order is `00`, `01`, `10`, `11`. Both probability laws must factor according to the graph.

The solver accepts **perfect DAGs**, where the parents of every node form a clique, and the three-node binary collider. The auditor accepts any supported-size DAG. An audit input is a JSON coupling matrix whose rows follow source-state order and whose columns follow target-state order.

### Specify parent-dependent costs

By default each node costs one unit when its source and target bits differ. To override that cost, supply a `cost_factors` object keyed by node name. Each entry is a square table for the node and its parents. A local bit string contains the parent bits in model order, followed by the node's bit. Rows enumerate those strings for the source and columns enumerate them for the target, both in lexicographic order. For one parent the order is `00`, `01`, `10`, `11`. Entries must be finite and nonnegative.

Choose **Parent-weighted fork** in the workbench or run the same fixture in the CLI.

```sh
python -m graphweft compare examples/parent_weighted_fork.json --summary
```

In the [parent-weighted fork](examples/parent_weighted_fork.json), a mismatch at C costs two units when source A is zero and four when source A is one. Ordinary OT can match C and pay a total of **1.0**. Graph-bicausal OT costs **2.5**, with **1.5** from C. The **Cost by node** table shows each term in the totals. Saved runs include the cost tables and verify them along with the resulting costs.

### Isolate the effect of a graph edge

Compare **Binary collider** and **Ordered control** in the example menu. Both use independent fair bits at A and B, with C equal to A XOR B in the source and B in the target. A mismatch at C costs two units.

| Graph | Ordinary OT | Graph-bicausal OT |
|---|---:|---:|
| [Collider](examples/binary_collider.json), A and B both point to C | 0.5 | 1.0 |
| [Ordered control](examples/ordered_control.json), adds A → B | 0.5 | 0.5 |

In the collider, the paired roots must be independent. The source's XOR is independent of the target's B, so C differs half the time. In the ordered graph, the B coupling can flip B when A is one. That matches C exactly and pays half a unit at B. Auditing the ordered plan under the collider graph flags that dependence on A at node B.

## Method and verification

The ordinary solver uses a full-coupling LP in SciPy/HiGHS. For perfect DAGs the constrained solver uses one LP over the paired state at each node and its parents. Linear constraints match each input’s local marginals and enforce consistency between overlapping tables. The conditional kernels reconstruct the plan. [Kernel characterization and graph-separable costs, Propositions 4.7 and 5.2–5.3](https://arxiv.org/html/2608.13716v1)

The collider solver minimizes the child cost separately at each paired parent context. A binary coupling is an interval because its `(0, 0)` mass fixes the other three entries. The root objective is bilinear in the two independent root couplings, so a minimum occurs at a pair of interval endpoints. The solver evaluates the four root combinations and reconstructs the selected plan.

The audit checks joint marginals, prescribed conditional marginals, and the dependence of each paired state on earlier pairs. Custom objectives are scaled by the sum of the maximum local costs when that sum is positive. Costs are displayed in their original units. Verification checks probability audits at an absolute tolerance of `1e-8` and custom objective values at that tolerance in solver units.

GraphWeft focuses on inspecting graph-specific plans. Existing implementations of time-adapted transport provide related numerical baselines. [AOTNumerics](https://github.com/stephaneckstein/aotnumerics) [PNOT](https://github.com/justinhou95/NestedOT)

```sh
python -m unittest discover -s tests -v
```

The tests check the cost gaps, the shared-coin counterexample, empty-graph decomposition, agreement with ordinary OT for a single node, and the collider solver against an independent enumeration.
