# When the same transport cost hides a different plan

For 725 days of Capital Bikeshare data, GraphWeft compares working-day and non-working-day rental patterns. On a first-order fit, both transport optima have **1.514581** expected mismatches across the three sampled hours. The ordinary plan shown in the report fails the graph audit. A graph-bicausal plan achieves that same cost while preserving the required conditional distributions. With a fuller fit to the same days, graph-bicausal transport costs **1.559937**, and the entire increase comes from evening mismatches.

## Open the reports

Start the [local workbench](../../README.md#browser-workbench), choose **Open run**, and load the two files below. In each report, select **Ordinary OT** in **Plan audit**. The chain report restores the search table and its saved alternative graph.

- The first-order report compares the chain with and without the morning-to-evening shortcut. [chain-search.json](chain-search.json)
- The full-history report compares two empirical laws on the graph with every forward edge. [full-history-run.json](full-history-run.json)

## Data and fitted laws

The UCI Bike Sharing Dataset aggregates 2011–2012 Capital Bikeshare rentals in Washington, DC. The study uses `cnt` at 08:00, 12:00, and 18:00 from `hour.csv` and splits days by the dataset's `workingday` flag. Six of 731 dates lack at least one selected hour, leaving 495 working days and 230 non-working days. A bit is 1 when the hourly count is at or above the pooled median for that hour. The cutoffs are 387, 229, and 419 rentals, respectively. [Hadi Fanaee-T, Bike Sharing Dataset, UCI, CC BY 4.0](https://doi.org/10.24432/C5W894)

| Observed state in hour order | `000` | `001` | `010` | `011` | `100` | `101` | `110` | `111` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Working days | 110 | 22 | 2 | 1 | 57 | 116 | 11 | 176 |
| Non-working days | 55 | 0 | 126 | 46 | 0 | 0 | 0 | 3 |

The first-order graph is `08:00 → 12:00 → 18:00`. For each group, the fit multiplies the morning frequency by the two transition frequencies, each conditional on the previous bit. The full-history graph adds `08:00 → 18:00` and fits the joint law using all eight empirical state frequencies. Each mismatch costs one unit. The graphs describe what history the model uses. The comparison is descriptive and uses the same observations for fitting and evaluation.

## What the audit reveals

| Comparison | Ordinary OT | Graph-bicausal OT | Gap |
|---|---:|---:|---:|
| First-order fit | 1.514581 | 1.514581 | 0 |
| Add `08:00 → 18:00` with the first-order laws fixed | 1.514581 | 1.514581 | 0 |
| Refit the laws using full history | 1.514581 | 1.559937 | 0.045356 |

In the first-order report, choose the **Node 18:00 · source conditional marginal** finding where both 12:00 bits are 0. In that context, the ordinary plan puts **0%** of working-day evenings above the cutoff. The working-day fit requires **45.25%**. The context accounts for **23.91%** of coupling mass. This finding describes the saved ordinary plan. The constrained plan shows that there is also an admissible plan at the ordinary optimum. [First-order comparison](chain-search.json)

The observed working days show why the fit matters. Among days with below-cutoff rentals at noon, high evening rentals occur on **22 of 132** days with a low morning and **116 of 173** days with a high morning. The first-order fit pools those histories and differs from the empirical daily law by **0.1597** in total variation on working days and **0.0188** on non-working days. Under the full-history refit, the expected evening mismatch rises from **0.423320** to **0.468676** when the graph constraints are enforced. [Full-history comparison](full-history-run.json)

| Common scale applied to all hourly cutoffs | First-order gap | Full-history gap |
|---|---:|---:|
| 90% | 0 | 0.087424 |
| 100% | 0 | 0.045356 |
| 110% | 0 | 0.003455 |

The positive full-history gap persists across these cutoffs. Its size is sensitive to binning. The shortcut experiment varies the graph with both fitted laws fixed, while the refit uses the empirical laws. The study gives an in-sample comparison for this dataset and these time points.

## Independent numerical comparison

AOTNumerics matched GraphWeft's ordinary and constrained costs for the synthetic two-node chain and all three bike-sharing comparisons. The largest absolute difference was below `5e-16`. The adapter passes both joint laws in the same bit order with the same Hamming cost. It calls upstream `solve_pot` for ordinary OT and `gurobi_bm` with both causal directions enabled for the time-adapted LP. The value comparison applies here because the graphs are sorted perfect DAGs, the laws are compatible, and the cost is coordinatewise. [AOTNumerics revision](https://github.com/stephaneckstein/aotnumerics/tree/6f2d706009c4cb55c6f488686b194f6024819a4e) · [Theorem 5.4](https://arxiv.org/html/2608.13716v1#S5.Thmtheorem4)

## Reproduce the study

The preparation script checks the archive's SHA-256, rebuilds both reports, and prints the counts, fit residuals, and cutoff sensitivity as JSON.

```sh
python -m pip install -e .
case_dir=$(mktemp -d)
curl --fail --location 'https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip' \
  --output "$case_dir/bike-sharing.zip"
python studies/bike_sharing/prepare.py "$case_dir/bike-sharing.zip" "$case_dir"
python -m graphweft verify-run "$case_dir/chain-search.json"
python -m graphweft verify-run "$case_dir/full-history-run.json"
```

The AOTNumerics comparison was run with Python 3.12, POT 0.9.6.post1, scikit-learn 1.8.0, and Gurobi 14.0.0. Its small LPs fit the size-limited Gurobi license. The comparison has these additional dependencies.

```sh
python -m pip install POT==0.9.6.post1 scikit-learn==1.8.0 gurobipy==14.0.0
git clone https://github.com/stephaneckstein/aotnumerics.git "$case_dir/aotnumerics"
git -C "$case_dir/aotnumerics" checkout --detach 6f2d706009c4cb55c6f488686b194f6024819a4e
python studies/bike_sharing/cross_check.py "$case_dir/aotnumerics" "$case_dir"
```
