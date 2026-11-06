# finvisor

Personal-finance analysis for a Revolut account, pulled through the
[Enable Banking](https://enablebanking.com) open-banking (PSD2) API.

- **`index.html`** — the web dashboard. Static, no build, no server: it parses your
  `transactions.csv` **in the browser** and nothing is uploaded. Also serves as the
  Enable Banking redirect page (shows the `?code=` to copy back).
  Live at <https://aminghuf.github.io/finvisor/> — drop your CSV on it.
- `connect.py` — Enable Banking client: consent → session → transactions + balances → `data/`.
- `analyze.py` — deterministic classification/categorization → `data/report.md`, `data/stats.json`.
- `narrate.py` — optional LLM narrative over `stats.json` (any OpenAI-compatible endpoint, incl. Ollama).
- `chart.py` — standalone SVG chart → `chart.html`.
- `categories.json` — merchant keyword rules, shared by `analyze.py` and the dashboard.
  Put personal keywords (names, etc.) in a gitignored `categories.local.json` with the same shape;
  its rules are checked first.

## Use

```bash
pip install pyjwt cryptography requests

# 1. consent (opens Revolut auth; you land back on the dashboard with a code)
python3 connect.py --redirect-url "https://aminghuf.github.io/finvisor/" --auth-only
# 2. pull data
python3 connect.py --redirect-url "https://aminghuf.github.io/finvisor/" --code <CODE>

# 3. dashboard, locally — auto-loads data/transactions.csv
python3 -m http.server 8000      # open http://localhost:8000

# optional
python3 analyze.py               # text report + stats.json
python3 narrate.py               # LLM narrative
```

## Dashboard

KPI tiles, monthly card-spending vs money-in, spending by category, top merchants,
recurring charges, all-outflows breakdown, and a searchable/sortable transaction table
with CSV export. Filter by account and period (3M/6M/12M/YTD/All); click a month,
category, merchant or flow to drill in. A loaded file is remembered in this browser's
local storage until you press **Forget data**.

"Spending" means card payments only — transfers between your own pockets and to
other people are shown separately. Only Revolut is covered (no cash/rent/other banks).

`data/` is gitignored: never commit transaction data to this public repo.
