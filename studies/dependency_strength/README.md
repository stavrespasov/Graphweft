# When two added edges become useful

We varied the strength of a dependency in a four-node synthetic model while keeping both input laws and the objective fixed across graph comparisons. Either added edge alone leaves the constrained optimum unchanged. Adding both edges lowers it only above strength 0.5. At strength 0.75, an ordinary plan still costs less than the best graph-bicausal plan on the complete ordered graph.

## Design

In each law, A, B, and C are independent fair bits. In the source, D equals A XOR B XOR C with probability `(1 + s) / 2` and is the opposite bit otherwise. In the target, D equals C with that same probability. The flip probability is shared between the laws. The parameter `s` runs from 0 (D is independent of its inputs) to 1 (D is determined by them). This extends the [deterministic interacting-edges example](../../examples/interacting_edges.json).

The base graph is a collider with A, B, and C pointing into D. We compare it with either or both of A → C and B → C added, and with the complete forward graph, which also adds A → B. Each law is compatible with every graph tested. A C mismatch costs 0.5 and a mismatch at any other node costs 1 in all five cases. The extra edges change what the C coupling may condition on.

## Costs at known strength

| Strength | Ordinary OT | Collider | Either edge into C | Both edges into C | Complete graph |
|---:|---:|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 | 0 | 0 |
| 0.25 | 0.0625 | 0.125 | 0.125 | 0.125 | 0.125 |
| 0.50 | 0.125 | 0.25 | 0.25 | 0.25 | 0.25 |
| 0.75 | 0.1875 | 0.375 | 0.375 | 0.25 | 0.25 |
| 1.00 | 0.25 | 0.50 | 0.50 | 0.25 | 0.25 |

For the collider or either single-edge expansion, at least one of A and B is unseen by the C coupling. The paired graph makes that unseen fair bit independent of the inputs available to the C coupling and of the resulting C pair. The two intended D values therefore disagree half the time. When they disagree, the prescribed D marginals differ by `s`. Matching C and using a maximal coupling at D achieves the lower bound `s / 2`.

When C can see both parents, it can flip whenever the source parity A XOR B is one. In those contexts, matching C costs `s` in expected D mismatches and flipping C costs 0.5. The parity is one half the time, so the optimum is `min(s, 0.5) / 2`. This is also the lower bound on the complete graph because extra information cannot change either the source parity frequency or the two costs in those contexts.

For ordinary transport, the event A XOR B XOR C XOR D = 1 has probability `(1 - s) / 2` in the source and 0.5 in the target. At least `s / 2` mass must cross between parity classes and each crossing costs at least 0.5. Ordinary transport attains `s / 4` by matching A, B, and D and maximally coupling C conditional on those three bits. Under a graph constraint, D comes after C in the node order. The ability to choose C using D explains the remaining gap at intermediate strengths.

An exhaustive search at strength 0.75 confirms that two added edges are needed to lower the cost, and even all three leave a gap of **0.0625**. The regression suite checks all 25 cases against the closed forms and against a separate full-coupling LP/MILP. [Independent solver test](../../tests/test_reference_transport.py)

## Estimating strength from finite samples

At true strength 0.55, adding both edges decreases the known-law constrained cost by 0.025. We simulated 2,000 fits per sample size with seed 82027. Each replicate has the specified number of independent observations from each law. The pooled number of parity flips is sufficient for the shared flip probability, so the script draws that count directly from a binomial distribution. It estimates the flip probability by its pooled frequency, clips the fitted strength to `[0, 1]`, and evaluates the resulting cost decrease using the closed form.

| Observations per law | Fits with positive edge savings | Median savings | 5th–95th percentile |
|---:|---:|---:|---:|
| 64 | 71.35% | 0.02344 | 0–0.08594 |
| 256 | 90.55% | 0.02539 | 0–0.05469 |
| 1,024 | 99.75% | 0.02490 | 0.00977–0.04006 |

Near the threshold, sampling noise can put the fitted strength below 0.5 even when the true graph expansion saves cost. This simulation assumes the XOR structure, fair roots, and shared flip probability are known. The percentages describe these simulated fits. Other dependency structures, mismatch costs, and estimation procedures can give different thresholds or savings.

## Reproduce and inspect

From the repository root, run with Python 3.10 or newer.

```sh
python -m pip install .
case_dir=$(mktemp -d)
python -m studies.dependency_strength.run --report "$case_dir/edge-search.json"
python -m graphweft verify-run "$case_dir/edge-search.json"
python -m graphweft serve --run "$case_dir/edge-search.json"
```

The script prints the cost table and sample-size sweep as JSON. Open the URL printed by the workbench, select the result with both edges under **Compare an added edge**, then choose **Inspect plan on original graph** to see which conditional checks that plan fails.

The four-bit laws have 16 states per side and a dense coupling has 256 cells. The saved search evaluates eight subsets of the three absent edges. The current solver supports four binary nodes, and its exhaustive graph search can evaluate at most 64 ordered graphs at that size. The [runtime and memory benchmarks](../../benchmarks/README.md) measure the supported sizes and detail what the measurements include.
