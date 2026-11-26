# Auditing graph-bicausal optimal transport on finite binary DAGs

## Abstract

GraphWeft computes ordinary and graph-bicausal optimal transport for probability laws on up to four binary nodes. It returns both couplings and identifies the positive-mass contexts where a candidate violates the prescribed conditional distributions. On a first-order fit to 725 days of Capital Bikeshare data, an ordinary optimum fails the graph audit while an admissible optimum attains the same cost. A full-history fit raises the constrained value by 0.045356. A study of 137 days of household appliance measurements produces a gap of 0.013190 under the same full-history graph and Hamming cost. Independent optimization formulations check the reported optima.

## 1. Problem and admissibility

Let $G$ be a directed acyclic graph with nodes in topological order. Write $P_i$ for the parents of node $i$. The two input laws $\mu$ and $\nu$ on $\{0,1\}^n$ each factor over $G$. For a candidate coupling of $X\sim\mu$ and $Y\sim\nu$, write $Z_i=(X_i,Y_i)$. Graph-bicausality requires paired kernels $K_i$ such that

$$
\pi(x,y)=\prod_{i=1}^{n}K_i(z_i\mid z_{P_i}),
\qquad
K_i(\cdot\mid z_{P_i})
\in\Pi\bigl(\mu_i(\cdot\mid x_{P_i}),\,\nu_i(\cdot\mid y_{P_i})\bigr).
$$

Here $\Pi$ is the set of couplings of its two arguments. The audit checks the joint marginals, compares the law of $Z_i$ given each positive-mass paired history with the law given just its paired parents, and compares both marginals of that parent-conditioned law with the model. In the shared-coin fork fixture, both child pairs use one coin. This creates conditional dependence between the children even though each child pair has the prescribed one-sided conditional marginals. [Obłój and Tuchilus, Proposition 4.7](https://arxiv.org/html/2608.13716v1#S4.Thmtheorem7) · [Shared-coin fixture](../examples/shared_coin_model.json)

Given a graph-separable cost, both problems minimize the same expectation.

$$
c(x,y)=\sum_{i=1}^{n} c_i(x_{P_i},x_i,y_{P_i},y_i),
\qquad
V_0=\min_{\pi\in\Pi(\mu,\nu)} E_\pi[c],
\qquad
V_G=\min_{\pi\in\Pi_G^{bc}(\mu,\nu)} E_\pi[c].
$$

The independent coupling is feasible for both problems, so $V_G\geq V_0$. When $V_G=V_0$, an admissible ordinary optimum exists. A solver can still return a different ordinary optimum that fails at a specific history. The audit evidence describes the selected plan.

## 2. Implementation

**Ordinary optimization.** GraphWeft encodes the input floats as dyadic rationals, normalizes their integer masses to a common supply and demand total, and solves a bipartite min-cost flow. It converts the flow back to floating-point probabilities and checks the reconstructed objective and marginals. [NetworkX network simplex](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.flow.network_simplex.html)

**Perfect DAGs.** A DAG is perfect when every pair of parents of a node is joined by an edge. Eliminate the nodes in reverse topological order. At a paired parent context, minimize the expected current family cost over the $2\times2$ couplings of the two prescribed Bernoulli marginals. Add the minimized function to the last parent's family, which contains every parent of the eliminated node. Retain the minimizing kernels to reconstruct the coupling. [Obłój and Tuchilus, Propositions 5.2–5.3](https://arxiv.org/html/2608.13716v1#S5.Thmtheorem2)

**Other DAGs.** Each local binary kernel is a line segment once its marginals are fixed. A joint outcome uses one factor per node, so its mass and the total objective are affine in the coordinate of any one local segment with the others fixed. Starting from a minimum on the product of segments, move one segment at a time to an endpoint that also minimizes the current objective. This gives an optimum with all kernels at endpoints. The implementation enumerates those choices while skipping unreachable contexts and optimizing the last node locally. [Solver implementation](../graphweft/transport.py)

## 3. Experiments

Each day becomes a three-bit vector from model-specific cutoffs at 08:00, 12:00, and 18:00. The objective counts expected bit mismatches. Bikeshare groups use the dataset's working-day flag. The household dataset uses calendar weekdays and weekends. The first-order Bikeshare fit conditions on the previous bit, while the full-history fits use the eight empirical state masses. [Bikeshare preparation](../studies/bike_sharing/prepare.py) · [Appliance-energy preparation](../studies/appliance_energy/prepare.py)

| Comparison | Days | Ordinary OT | Graph-bicausal OT | Difference |
|---|---:|---:|---:|---:|
| Bikeshare, first-order fit | 725 | 1.514581 | 1.514581 | 0 |
| Bikeshare, full-history fit | 725 | 1.514581 | 1.559937 | 0.045356 |
| Household appliance energy, full-history fit | 137 | 0.292132 | 0.305321 | 0.013190 |

In the first-order Bikeshare witness, the ordinary plan assigns 0% probability to an above-cutoff working-day evening when both noon bits are 0. The fitted law prescribes 45.25% for that context, which carries 23.91% of the plan's mass. Adding the morning-to-evening edge with the first-order laws fixed leaves the optimum unchanged. Refitting the laws using full history produces the positive gap. The full-history gaps in both datasets come from 18:00 and stay positive when all cutoffs are scaled to 90% or 110% of their medians. [Bikeshare study](../studies/bike_sharing/README.md) · [Household energy study](../studies/appliance_energy/README.md)

A controlled four-node experiment varies a noisy parity dependency and holds both laws and all mismatch costs fixed across five graphs at each setting. Adding both edges into an intermediate node lowers the optimum only above strength 0.5. The threshold follows from the costs of mismatching the intermediate and final nodes. The study derives closed-form optima and simulates how often a finite-sample fit detects the benefit from adding the edges. [Four-node dependency-strength study](../studies/dependency_strength/README.md)

## 4. Verification and performance

A separate reference program uses a full-coupling LP for ordinary transport and a full-coupling MILP for graph-bicausal transport. It enforces both prescribed conditional marginals at every paired history. For histories with the same paired parents, a shared binary choice fixes a zero cell in the local $2\times2$ kernel. The fixed marginals determine the rest of the kernel. The endpoint argument justifies this restriction for value checks. Tests cover 128 seeded instances across all 64 four-node edge patterns in one topological order, analytic fixtures, and the three experiment rows above. Saved witnesses are replayed and audited separately. [Independent reference](../tests/reference_transport.py) · [Reference tests](../tests/test_reference_transport.py)

For the Bikeshare study, the ordinary and constrained values also agree with AOTNumerics to within $5\times10^{-16}$. Theorem 5.4 supplies the equality with time-adapted Wasserstein values for compatible laws on sorted perfect DAGs and the coordinatewise metric cost used here. Related software includes AOTNumerics and PNOT. The contribution here is a finite implementation with graph-specific audit evidence and reproducible reports. [Theorem 5.4](https://arxiv.org/html/2608.13716v1#S5.Thmtheorem4) · [AOTNumerics](https://github.com/stephaneckstein/aotnumerics) · [PNOT](https://github.com/justinhou95/NestedOT)

On one Linux host, the seeded benchmark's four-node comparisons had median wall times of 3.1–8.9 ms. An exhaustive 64-graph edge search took 366.8 ms median with about 879 KiB of peak traced allocations. The dense coupling has $4^n$ cells, and endpoint enumeration can be exponential in the number of active parent contexts. [Benchmark method and reproduction command](../benchmarks/README.md)

## 5. Scope

The experiments are in-sample, use binary observations at three times, and assume the supplied information graph. They illustrate the effect of coupling constraints on fitted laws. Causal effect estimation and out-of-sample forecasting are separate questions. The household data cover one home and the gaps depend on the cutoff choice. The implementation accepts at most four binary nodes, uses numerical tolerances on witness reconstruction, and reports a transport objective for the supplied cost. Metric properties require separate hypotheses. [Cheridito and Eckstein, Optimal transport and Wasserstein distances for causal models](https://arxiv.org/abs/2303.14085) · [Obłój and Tuchilus, Graph Causal Optimal Transport and Wasserstein Distances](https://arxiv.org/abs/2608.13716)
