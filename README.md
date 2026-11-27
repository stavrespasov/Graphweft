# GraphWeft

[![v0.1.0 DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24582991.svg)](https://doi.org/10.5281/zenodo.24582991)

GraphWeft computes ordinary and **graph-bicausal optimal transport** for compatible laws on one to four binary nodes. Given a directed acyclic graph, it returns both optimal couplings and pinpoints the conditional probabilities that make a plan inadmissible.

## Reproducible studies

A saved ordinary plan for working-day versus non-working-day Bikeshare rentals achieves the same objective as an admissible plan. In a below-cutoff noon context, it assigns a busy working-day evening 0% probability even though the fitted law requires 45.25%. For comparisons of energy demand or traffic by time of day, a plan audit can reveal when an apparently good match changes the relationships between early and later readings.

| Comparison | Ordinary OT | Graph-bicausal OT | Gap |
|---|---:|---:|---:|
| [Capital Bikeshare, first-order fit](studies/bike_sharing/README.md) | 1.514581 | 1.514581 | 0 |
| [Capital Bikeshare, full-history fit](studies/bike_sharing/full-history-run.json) | 1.514581 | 1.559937 | 0.045356 |
| [Household appliance energy, full-history fit](studies/appliance_energy/README.md) | 0.292132 | 0.305321 | 0.013190 |

Costs are expected mismatches across three binary time slots. Each study includes data preparation instructions and a saved witness. The [technical note](docs/technical-note.md) gives the mathematical formulation, independent checks, and limits. The [benchmarks](benchmarks/README.md) record runtime and traced allocations over the supported problem sizes.

To reproduce the comparison in the workbench from a fresh checkout, follow the [reviewer walkthrough](studies/bike_sharing/REVIEW.md). A [controlled four-node study](studies/dependency_strength/README.md) holds both laws and the cost fixed across graph comparisons and shows when two added edges start to lower the optimum.

The four-node result gives a counterexample to diminishing returns. A seven-node extension shows why adding the best single edge at each step can miss almost all the possible savings. The larger cases use analytic optima. [Edge complementarity and greedy search](studies/edge_complementarity/README.md)

## Browser workbench

From a repository checkout or extracted source distribution, use Python 3.10 or newer in a virtual environment.

```sh
python -m pip install -e .
python -m graphweft serve
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The fork example opens with both coupling matrices on the same color scale. Select either plan in the audit panel to see the failed conditions or confirm the checks passed. Choose **Shared-coin audit** to compare the two conditional distributions at node C. Open **Edit inputs** to run your own model or supply a coupling matrix. The workbench uses the local Python solver.

## Save and verify a run

Select **Save run** after a comparison or audit. The JSON file contains the inputs, coupling matrices, costs where applicable, audit findings, an input checksum, and the Python, NumPy and solver library versions. **Open run** recomputes the optimum with the installed solver and checks the saved witness before displaying it. Any feasible plan that attains the same cost within solver tolerance can pass replay.

```sh
python -m graphweft verify-run path/to/saved-run.json
```

Use `python -m graphweft serve --run path/to/saved-run.json` to verify a run or edge-search report before the workbench starts and display it when the page opens.

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

### Check rare states

The **Rare-state chain** preset has a source state with probability `1e-12`. Ordinary OT costs `1e-12`. The graph-constrained plan must preserve the target's conditional law of B even where A is rare, and costs `2e-12`. Audits identify missing states, unexpected states, and states with the wrong positive mass. [Rare-state fixture](examples/rare_state_chain.json)

```sh
python -m graphweft compare examples/rare_state_chain.json --summary
```

## Use your own model

Start from [the chain fixture](examples/binary_chain.json). Define one to four binary nodes in topological order and list the parents of each node. The source and target vectors assign mass to lexicographically ordered bit strings. For two nodes, the order is `00`, `01`, `10`, `11`. Both probability laws must factor according to the graph. Reconstruction must preserve every zero and match each positive state mass within a relative tolerance of `1e-10`.

The solver and auditor accept any DAG on one to four binary nodes. An audit input is a JSON coupling matrix whose rows follow source-state order and whose columns follow target-state order.

### Specify parent-dependent costs

By default each node costs one unit when its source and target bits differ. To override that cost, supply a `cost_factors` object keyed by node name. Each entry is a square table for the node and its parents. A local bit string contains the parent bits in model order, followed by the node's bit. Rows enumerate those strings for the source and columns enumerate them for the target, both in lexicographic order. For one parent the order is `00`, `01`, `10`, `11`. Entries must be finite and nonnegative.

Choose **Parent-weighted fork** in the workbench or run the same fixture in the CLI.

```sh
python -m graphweft compare examples/parent_weighted_fork.json --summary
```

In the [parent-weighted fork](examples/parent_weighted_fork.json), a mismatch at C costs two units when source A is zero and four when source A is one. Ordinary OT can match C and pay a total of **1.0**. Graph-bicausal OT costs **2.5**, with **1.5** from C. The **Cost by node** table shows each term in the totals. Saved runs include the cost tables and verify them along with the resulting costs.

### Isolate the effect of a graph edge

Choose **Binary collider**, open **Compare an added edge**, and compare A → B. Both graphs use independent fair bits at A and B, with C equal to A XOR B in the source and B in the target. A mismatch at C costs two units.

```sh
python -m graphweft compare-edge examples/binary_collider.json A B --summary
```

| Graph | Ordinary OT | Graph-bicausal OT |
|---|---:|---:|
| [Collider](examples/binary_collider.json), A and B both point to C | 0.5 | 1.0 |
| [Ordered control](examples/ordered_control.json), adds A → B | 0.5 | 0.5 |

In the collider, the paired roots must be independent. The source's XOR is independent of the target's B, so C differs half the time. In the ordered graph, the B coupling can flip B when A is one. That matches C exactly and pays half a unit at B. Select **Inspect plan on original graph** to see the audit flag that dependence on A at node B.

The comparison accepts a missing edge that follows the model's node order. The probability laws stay fixed, and any cost table affected by the new parent is expanded to give every source and target state pair the same cost as before. Use **Save expanded run** to open or verify the new plan independently. The full CLI output includes both runs as JSON objects and the audit of the expanded plan on the original graph.

Choose **Four-node collider** to see the effect of an edge upstream of another node. Here the source uses `D = A XOR B XOR C` and the target uses `D = B XOR C`. Adding A → C lets the plan flip C when A is one. This eliminates mismatches at D and reduces the constrained cost from **0.5 to 0.25**. The audit flags C's dependence on A under the original graph. [Four-node fixture](examples/four_node_collider.json)

```sh
python -m graphweft compare-edge examples/four_node_collider.json A C --summary
```

### Rank all missing edges

In **Compare an added edge**, select **Compare all edges**. GraphWeft adds each candidate to the original graph on its own and ranks the candidates by constrained cost decrease. Select an edge to inspect its plan against the original graph or save the expanded run. A decrease within solver tolerance is reported as zero. Several plans can attain the same cost, and the audit describes the selected plan.

```sh
python -m graphweft scan-edges examples/four_node_collider.json --summary
```

| Added edge | Constrained cost | Decrease from 0.50 |
|---|---:|---:|
| A → C | 0.25 | 0.25 |
| A → B | 0.50 | 0 |

Omit `--summary` for the original run and each candidate's expanded run and cross-graph audit. A graph that already contains every forward edge returns an empty list.

### Compare edge combinations

Select **Interacting edges**, open **Compare an added edge**, and choose **Compare edge combinations**. GraphWeft searches every subset of missing forward edges and shows one cheapest graph for each number of additions. Select a result to audit its plan against the original graph or save the expanded run.

```sh
python -m graphweft search-edges examples/interacting_edges.json --summary
```

| Number of added edges | Best constrained cost | Cost decrease |
|---:|---:|---:|
| 0 | 0.50 | 0 |
| 1 | 0.50 | 0 |
| 2 | 0.25 | 0.25 |
| 3 | 0.25 | 0.25 |

The source uses `D = A XOR B XOR C` and the target uses `D = C`. Together, A → C and B → C let the coupling flip C exactly when A and B differ. This removes mismatches at D and reaches the ordinary optimum of 0.25. [Interacting-edges fixture](examples/interacting_edges.json)

The search keeps the model's node order. It reports the fewest added edges needed to reach the ordinary cost within solver tolerance. When a gap remains after every forward edge is added, the reported minimum is `null`. The three-node fork is an example where the gap remains. At the four-node limit, the search evaluates at most 64 graphs, including the original.

Choose **Save edge search** to keep the original comparison, a winning plan for each number of additions, and the audits against the original graph. **Open run** verifies the file and restores the search table. Verification reruns the exhaustive search, checks the minimum edge count, and accepts a different winning combination if it attains the same cost within solver tolerance.

The full CLI output is the same versioned report. Use it to verify the entire search, including the claim that two edges are necessary in this example.

```sh
python -m graphweft search-edges examples/interacting_edges.json > edge-search.json
python -m graphweft verify-run edge-search.json
```

## Method and verification

The ordinary solver uses integer min-cost flow. It encodes the input floats as integer weights and uses a common supply and demand total, so the solver preserves small positive masses during optimization. The returned plan uses floating-point probabilities. [NetworkX network simplex](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.flow.network_simplex.html)

A graph-bicausal coupling factors as a product of paired node kernels. Each kernel depends on the source and target parents of that node and must have the two conditional marginals prescribed by the input laws. [Kernel characterization, Proposition 4.7](https://arxiv.org/html/2608.13716v1#S4.Thmtheorem7)

For perfect DAGs, where every node's parents form a clique, the constrained solver works backward. It minimizes the local cost plus all downstream terms already assigned to that node. It then adds the minimized cost as a function on the paired parents to the family of the last parent in node order. All those parents fit in that family because they form a clique. The selected kernels reconstruct the plan, including small positive histories. [Dynamic programming, Propositions 5.2–5.3](https://arxiv.org/html/2608.13716v1#S5.Thmtheorem2)

For other DAGs, the solver searches endpoints of the binary coupling intervals. At each paired parent context, the `(0, 0)` mass fixes the other three entries. Each joint outcome multiplies one kernel entry per node, so the expected cost is affine in each interval coordinate when the others are fixed. A minimum therefore occurs at some combination of endpoints. The search skips unreachable contexts and minimizes the final node's cost independently at each of its parent contexts. The number of combinations can grow exponentially, so the implementation is scoped to four nodes.

The audit checks joint marginals, prescribed conditional marginals, and the dependence of each paired state on earlier pairs. Joint marginal support must agree with the model. Each positive state mass is checked at a relative tolerance of `1e-8`, and conditional distributions are checked at an absolute tolerance of `1e-8`. Custom objectives are scaled by the sum of the maximum local costs when that sum is positive. Costs are displayed in their original units and verified at `1e-8` in solver units. Legacy run files are replayed with the current checks.

GraphWeft focuses on inspecting graph-specific plans. Existing implementations of time-adapted transport provide related numerical baselines. [AOTNumerics](https://github.com/stephaneckstein/aotnumerics) [PNOT](https://github.com/justinhou95/NestedOT)

### Check optima with an independent solver

```sh
python -m pip install -e '.[test]'
python -m unittest discover -s tests -p test_reference_transport.py -v
```

The test-only reference uses the full coupling matrix as its decision variables. A linear program checks ordinary OT. A mixed-integer program checks graph-bicausal OT by enforcing the prescribed marginals at each paired history. Where histories share a paired parent context, a single binary variable selects a common zero cell of their `2 × 2` kernels. Their fixed marginals then determine the same kernel. An optimum exists at an endpoint in each binary kernel's coupling interval, so the reference can make this restriction while preserving the optimum.

These checks cover 128 seeded cases across all 64 four-node edge patterns in a fixed node order, six synthetic fixtures, three real-data comparisons, all eight configurations in the interacting-edges search, and 25 cases in the dependency-strength sweep. Generated cases include parent-dependent laws, structural zeros, and asymmetric costs. The reference uses floating-point solvers. The separate rare-state regressions use analytic optima for masses down to `1e-100`.

Run the full suite with the same test dependencies.

```sh
python -m unittest discover -s tests -v
```

The full suite also checks the shared-coin counterexample, empty-graph decomposition, single-node agreement with ordinary OT, and the collider solver against independent enumeration. Edge comparison tests check that adding a parent preserves the entire cost matrix and that both resulting runs can be verified.

The failure-mode inventory maps model validation, numerical, file replay, server, browser, and study failures to their regression tests. It includes commands for running the browser suite. [Failure modes and regression checks](docs/failure-modes.md)

## Citation and licenses

Use GitHub's **Cite this repository** panel or the [citation metadata](CITATION.cff) to cite GraphWeft. The software is under the [MIT license](LICENSE).

UCI distributes both source datasets under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This repository contains derived binary models, summaries, and transport reports. The reproduction instructions download the original archives from UCI, and each case study identifies its source and describes the transformations. [Capital Bikeshare](studies/bike_sharing/README.md) · [Household appliance energy](studies/appliance_energy/README.md)
