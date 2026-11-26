# The cost of preserving household energy histories

Across 137 complete days of household appliance measurements, ordinary optimal transport matches weekday and weekend patterns with **0.292132** expected mismatches. Enforcing the full-history graph increases the minimum to **0.305321**. The entire **0.013190** gap comes from the 18:00 mismatch term. [Replayable comparison](full-history-run.json)

## Data and model

The UCI Appliances Energy Prediction dataset records energy use in a low-energy house in Belgium. We use the `Appliances` reading in Wh from the rows stamped 08:00, 12:00, and 18:00 in `energydata_complete.csv`. These are individual measurements from the 10-minute series. January 11, 2016 lacks a selected time and is excluded. The remaining dates include 99 weekdays and 38 Saturdays or Sundays. Holidays follow their calendar weekday. [Luis Candanedo, Appliances Energy Prediction, UCI, CC BY 4.0](https://doi.org/10.24432/C5VC8G)

A bit is 1 when the reading meets or exceeds the pooled median for its time. The cutoffs are **60, 80, and 100 Wh**. Each group uses the empirical probabilities for the eight states in lexicographic order. The graph includes every forward edge in hour order, so the evening kernel can use both earlier readings. Each mismatch costs one unit.

| Group | `000` | `001` | `010` | `011` | `100` | `101` | `110` | `111` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Weekdays | 11 | 18 | 5 | 12 | 9 | 15 | 6 | 23 |
| Weekends | 2 | 3 | 6 | 6 | 4 | 4 | 3 | 10 |

| Time | Ordinary OT | Graph-bicausal OT | Difference |
|---|---:|---:|---:|
| 08:00 | 0.017278 | 0.017278 | 0 |
| 12:00 | 0.193248 | 0.193248 | 0 |
| 18:00 | 0.081606 | 0.094795 | 0.013190 |
| Total | 0.292132 | 0.305321 | 0.013190 |

The gap is **0.001869** when every cutoff is scaled to 90% and **0.025800** at 110%. It is positive across these cutoffs and its size depends on the binning. The numbers describe one home, and the same days are used to fit and compare the two laws.

## Replay and reproduce

From the repository root, install GraphWeft and open the checked-in witness. Expand **Cost by node** to locate the gap.

```sh
python -m pip install .
python -m graphweft verify-run studies/appliance_energy/full-history-run.json
python -m graphweft serve --run studies/appliance_energy/full-history-run.json
```

To rebuild the witness and the cutoff sweep, download the pinned archive and pass it to the preparation script.

```sh
case_dir=$(mktemp -d)
curl --fail --location 'https://archive.ics.uci.edu/static/public/374/appliances+energy+prediction.zip' \
  --output "$case_dir/appliances.zip"
python -m studies.appliance_energy.prepare "$case_dir/appliances.zip" "$case_dir"
python -m graphweft verify-run "$case_dir/full-history-run.json"
```

The script checks the archive's SHA-256 before reading it, writes the median-cutoff report, and prints state counts and costs at all three cutoff settings. The regression suite checks the reported optima against a separate full-coupling LP/MILP formulation. [Independent comparison test](../../tests/test_reference_transport.py)
