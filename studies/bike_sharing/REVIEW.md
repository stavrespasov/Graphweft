# Review the Capital Bikeshare comparison

Allow about 10 minutes with a GraphWeft checkout and Python 3.10 or newer. Both reports come with the checkout. The workbench uses a local Python server.

## Start with the saved report

From the repository root, create a virtual environment and install GraphWeft.

```sh
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m graphweft serve --run studies/bike_sharing/chain-search.json
```

On Windows, run these commands in PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m graphweft serve --run studies/bike_sharing/chain-search.json
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) and look for **Saved edge search verified.** If port 8765 is in use, add `--port 8766` and open the URL printed in the terminal. Stop the workbench with Ctrl+C when finished.

## Follow the evidence

1. Compare the two costs in **Transport plans**. In **Plan audit**, select **Ordinary OT** and choose finding **5 · Node 18:00 · source conditional marginal**. Check that **Paired parents** reads `12:00 = (0, 0)`. A 0 means the rental count is below the hourly cutoff. The source is working days and outcome 1 means the evening count meets or exceeds the cutoff. What probabilities does the plan give that outcome, and what does the fitted model require?
2. Switch to **Graph-bicausal OT** in **Plan audit**. Did its audit pass? In **Compare an added edge**, select the saved **08:00 → 18:00** result. Does the cost change when the graph gains this edge with both fitted laws held fixed?
3. Click **Open run** and choose `studies/bike_sharing/full-history-run.json`. Expand **Cost by node**. Which hour accounts for the gap? This report also refits both laws using full history, so the difference between the reports includes a change in the fitted laws.

The expected values, fit definitions, and raw-data reproduction commands are in the [case study](README.md).

## Send feedback

Record your OS, Python version, and browser, along with the first step where you got stuck or had to guess and any error text. In your own words, explain how two plans can have the same cost and different audit results. If you work with transport plans, say what you would use this evidence for or what would keep you from using it.
