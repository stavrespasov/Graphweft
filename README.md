# GraphWeft prototype

Compare two distributions over a shared binary DAG under ordinary and graph-bicausal optimal transport. The auditor explains failed conditional constraints for a whole coupling.

## Run locally

Use Python 3.10 or newer with NumPy and SciPy. From this checkout, install the project in a virtual environment if those dependencies are missing.

```sh
python -m pip install -e .
python -m graphweft compare examples/binary_chain.json --summary
python -m graphweft compare examples/binary_fork.json --summary
python -m graphweft audit examples/shared_coin_model.json examples/shared_coin_plan.json --summary
python -m unittest discover -s tests -v
```

The chain has Hamming costs **0.5** ordinary and **1** graph-bicausal. The fork gives **1** and **1.5**. Their constrained plans pass the audit. The shared-coin input fails at node C. Given the paired parent A and the paired history B, the probabilities of the four possible (source, target) outcomes are `[0.5, 0, 0, 0.5]`. Conditioning on the paired parent alone gives `[0.25, 0.25, 0.25, 0.25]`. The failed audit exits with code 1 and prints its evidence. Input or solver errors exit with code 2.

Omit the summary flag to see full coupling matrices and every failed conditional. For audit, the plan file is the JSON matrix itself, with rows in source-state order and columns in target-state order. Both use lexicographic bit strings in the model's node order.

## Input and method

A model gives one to four binary nodes in topological order, the parents of each node, and flat source and target probability vectors. Source and target must factor according to the supplied graph. Probability sums within 1e-10 of one are normalized for floating-point round-off. The solver uses Hamming cost and accepts perfect DAGs, where each node's parents form a clique. The plan audit also accepts other DAGs within the same size limit. Audit tolerances apply to reconstructed marginals and conditional probabilities.

For a node i, the LP stores the joint mass of its paired state and its paired parents. For each parent context, constrain the two one-sided sums of the local table to equal the context mass times the input conditional probabilities. The parent context mass comes from projecting the table of the last parent in topological order. Every parent occurs in that table because the DAG is perfect. At roots, total table mass is one. The sum of the local Hamming objectives is the global objective.

After solving, divide each positive-mass row by its context mass and multiply the resulting kernels in topological order. Zero-mass rows use the product of the required local marginals when evaluating the factorization. A post-solve audit checks both joint marginals, both local conditional marginals, and whether the pair at each node has the same distribution given all earlier pairs as it does given its paired parents alone. It checks the returned plan at a declared absolute tolerance and recomputes its objective.

The theoretical basis is the kernel characterization in Proposition 4.7 and the family inclusion property in Proposition 5.2. This prototype uses finite floating-point LPs and numerical audits. [Obłój and Tuchilus, v1](https://arxiv.org/html/2608.13716v1)

For related implementations of time-adapted transport and numerical comparisons, see [AOTNumerics](https://github.com/stephaneckstein/aotnumerics) and [PNOT](https://github.com/justinhou95/NestedOT). The first GraphWeft milestone is the graph-specific audit of the plans, using a separate unrestricted SciPy LP as the ordinary baseline.
