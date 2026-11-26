# GraphWeft failure modes

The table connects foreseeable failures to executable checks for the current four-node local workbench. The solver is checked against analytic cases, an independent LP and MILP, and invariants that must hold when the same problem is encoded differently.

| Failure | Regression check |
|---|---|
| Cyclic or out-of-order parents, repeated nodes, unsupported graph size, or incompatible laws | Reject invalid graphs and reconstructed laws. Test known compatible models across every four-node edge pattern. [Model invariants](../tests/test_model_invariants.py) · [Binary graphs](../tests/test_binary_graph.py) · [Rare states](../tests/test_rare_states.py) |
| Missing or repeated JSON fields, invalid encodings, excessive nesting, nonfinite numbers, booleans coerced to probabilities or costs | Reject duplicate keys, nonfinite JSON numbers, and mixed boolean arrays through the CLI, HTTP decoder, and editor. Enforce the same 64-level nesting limit on each Python release. Validate numeric shapes and graph constraints before solving. [CLI](../tests/test_cli.py) · [Model invariants](../tests/test_model_invariants.py) · [Workbench HTTP](../tests/test_workbench.py) · [Browser](../tests/browser/test_workbench_browser.py) |
| Graph labels or axes are reordered, or source and target are swapped | Remap law and cost tables to a different valid topological order. Transpose asymmetric costs and the witness when swapping source and target. Verify both optima and independently audit each remapped witness. [Model invariants](../tests/test_model_invariants.py) |
| Solver returns a plausible but incorrect optimum | Compare the two optima and per-node costs against full-coupling LP and MILP references on 128 generated models and published fixtures. Check all eight configurations of the interacting-edges example independently. [Reference solver checks](../tests/test_reference_transport.py) |
| Rare or impossible states are lost, invented, or given the wrong amount of mass | Check states as rare as `1e-100`, reject support changes below absolute tolerance, and enforce relative accuracy on positive state masses. [Rare states](../tests/test_rare_states.py) |
| A coupling has correct marginals while paired history leaks through the graph | Reject the shared-coin coupling, check source and target conditionals separately, and replay saved audit evidence. [Audit and transport](../tests/test_prototype.py) · [Saved runs](../tests/test_experiments.py) |
| Cost arithmetic introduces overflow, scale-dependent behavior, or a negative numerical gap | Exercise large, small, and zero objectives and replay an old negative-roundoff result. [Cost factors](../tests/test_costs.py) · [Saved runs](../tests/test_experiments.py) |
| Graph edits accidentally change the cost or laws, or a greedy scan misses interacting edges | Check each full cost matrix after parent expansion, verify known synergies and remaining gaps, and replay the maximum 64-configuration search within the file budget. [Edge studies](../tests/test_edge_study.py) |
| A saved document is edited, truncated, too large, or claims the wrong best combination | Check size boundaries, checksums, graph identity, feasibility, optimality, audit evidence, and minimality. Accept valid alternate optimizers and legacy field layouts. [CLI](../tests/test_cli.py) · [Saved runs](../tests/test_experiments.py) · [Edge search replay](../tests/test_edge_replay.py) |
| A request comes from an unexpected host or origin, declares an invalid length, or stalls or disconnects | Exercise loopback routing, media types, input and replay size bounds, short bodies, disconnected reads and writes, and a total input deadline that also covers partial headers. Verify a stalled connection releases its slot. [Workbench HTTP](../tests/test_workbench.py) |
| A solver fails or enough requests overlap to exhaust capacity | Inject a solver exception, submit different models concurrently, and repeatedly fill the solve slots. Check that the service returns a retryable response, examples remain available, and valid work resumes as slots free up. [Workbench HTTP](../tests/test_workbench.py) |
| An older browser response arrives after the user switches models or operations | Hold a response, switch to a newer result, then release the earlier response. Check that the current model and audit stay visible. [Browser](../tests/browser/test_workbench_browser.py) |
| The browser cannot load examples, a response body stalls, or a bad edit or upload fails | Retry startup in place, recover from busy and timed-out requests, preserve the draft, and exercise keyboard selection and report replay at desktop and mobile widths. [Browser](../tests/browser/test_workbench_browser.py) |
| Packaged assets disappear or dependencies change across browsers and Python releases | Automatic CI runs the regression suite on Python 3.10, 3.12, and 3.14 and exercises the installed workbench in Chromium, Firefox, and WebKit on Linux. The manual desktop workflow adds macOS and Windows checks. [Workflow](../.github/workflows/verification.yml) |
| The study archive changes, dates have missing hours, or binning and fitting silently change the model | Reject a replaced archive, test complete-day selection and cutoff boundaries, verify zero-mass parent contexts, and replay both committed reports. [Study inputs](../tests/test_study_inputs.py) · [Saved runs](../tests/test_experiments.py) |

## Run the checks

```sh
python -m pip install -e '.[test,browser-test]'
python -m unittest discover -s tests -v
python -m playwright install chromium
python -m unittest discover -s tests/browser -v
```

Set `GRAPHWEFT_BROWSER` to `firefox` or `webkit` after installing that Playwright browser. `GRAPHWEFT_CHROMIUM` can point to an installed Chromium executable. Use **Run workflow** in GitHub Actions to exercise the Windows and macOS jobs.

## Recovery behavior

The local server admits up to 16 connections and four simultaneous solve, audit, or replay requests. An excess request gets HTTP 503 with `Retry-After` set to one second. Each connection has five seconds to deliver its request. The workbench times out a fetch after 30 seconds, keeps the current input fields, and enables retry. A server restart restores capacity if a solver stays stuck. Saved run files can be reopened after restarting.

The load tests cover bounded local bursts and recovery. Capacity under sustained service load needs its own measurement. Upstream data availability and the optional AOTNumerics solver license are checked when reproducing the [external comparison](../studies/bike_sharing/README.md#reproduce-the-study).
