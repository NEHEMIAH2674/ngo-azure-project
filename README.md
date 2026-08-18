# d.light Call-Centre Effectiveness Pipeline

A small, production-shaped analytics pipeline answering four questions about call-centre effectiveness for d.light's PAYGo solar business across Kenya, Uganda, Tanzania and Nigeria, built for the BI Analytics Engineer case study.

See **[WRITEUP.md](WRITEUP.md)** for the four metrics' answers, data gaps found, assumptions made, and recommendations — this file only covers how to run it.

## Architecture

```
data/raw/*.csv ──┐
                 ├──▶ ingestion/load_csv_to_bq.py ──▶ BigQuery raw.*  (append-only landing, byte-for-byte)
exchangerate     │
-api.com    ─────┘──▶ ingestion/api/fx/ (hook → operator) ──▶ BigQuery raw.fx_rates

BigQuery raw.* ──▶ dbt staging ──▶ dbt intermediate ──▶ dbt marts ──▶ (dashboard, not yet built)

Dagster (orchestration/) wires all of the above into one graph: raw ingestion
assets → dbt's staging/intermediate/marts graph, with asset checks and a
daily schedule.
```

- **Ingestion** (`ingestion/`): a from-scratch Python loader, not a managed connector — see [WRITEUP.md](WRITEUP.md) for why. Idempotent via whole-file content hash (`_load_manifest`); raw lands with zero transformation.
- **Transformation** (`dbt/`): staging (1:1 typed/cleaned per source) → intermediate (coding match, payment attribution) → marts (the four metrics).
- **Orchestration** (`orchestration/`): Dagster wraps ingestion + dbt into one asset graph.
- **CI** (`.github/workflows/ci.yml`): lint, unit tests, and a full `dbt build` against an isolated CI BigQuery dataset on every push.

## Prerequisites

- Python 3.12+
- A Google Cloud project with BigQuery enabled (this repo targets `npd-01`; change `GCP_PROJECT_ID` in `.env` to point at your own)
- `gcloud` CLI, authenticated (`gcloud auth application-default login`)
- (Optional, for Metric 3 in USD) a free API key from [exchangerate-api.com](https://www.exchangerate-api.com/)

## Setup

```bash
cp .env.example .env
# edit .env: set GCP_PROJECT_ID, and EXCHANGE_RATE_API_KEY if you have one
pip install -r requirements.txt
```

Auth note: this GCP org disables service-account key export (`constraints/iam.disableServiceAccountKeyCreation`), so there is no JSON key anywhere in this repo or on disk. Locally, auth is your own `gcloud` ADC impersonating a narrowly-scoped service account (`dlight-case-study@npd-01.iam.gserviceaccount.com`, granted only `bigquery.dataEditor` + `bigquery.jobUser`):

```bash
gcloud auth application-default login
gcloud iam service-accounts add-iam-policy-binding dlight-case-study@npd-01.iam.gserviceaccount.com \
  --member="user:<your-email>" --role="roles/iam.serviceAccountTokenCreator"
```

## Run it end to end

```bash
make ingest      # load the 4 CSVs into BigQuery raw.* (idempotent: re-running is a no-op)
make fx          # fetch/cache missing FX rates (no-ops gracefully if no key is set)
make transform   # dbt seed + run + test: builds staging → intermediate → marts
make test        # pytest on ingestion + dbt test again, standalone
```

Or the whole thing via Dagster (recommended — this is what "runs every morning against yesterday's data" in production):

```bash
make dagster     # opens the Dagster UI at localhost:3000; click "Materialize all"
```

What you should see: BigQuery ends up with two dataset groups — `dlight_raw` (4 landing tables + `fx_rates` + `_load_manifest`, all untouched CSV data) and `dlight_analytics_{staging,intermediate,marts}` (12 dbt models). `dbt build` / the Dagster run should finish with **46/46 steps passing** (1 seed, 7 tables, 5 views, 33 tests).

### Deleting and rebuilding from scratch

```bash
bq rm -r -f --dataset $GCP_PROJECT_ID:dlight_raw
bq rm -r -f --dataset $GCP_PROJECT_ID:dlight_analytics_staging
bq rm -r -f --dataset $GCP_PROJECT_ID:dlight_analytics_intermediate
bq rm -r -f --dataset $GCP_PROJECT_ID:dlight_analytics_marts
make ingest && make fx && make transform
```

Everything regenerates from `data/raw/*.csv` — no other manual setup required.

### A new day of data

Drop a new day's 4 CSVs into `data/raw/` (same filenames) and re-run `make ingest`. The loader diffs by whole-file content hash, so it only loads what's actually new; nothing here needs editing.

## Running tests

```bash
pytest ingestion/tests -v     # 8 unit tests: parsing, rejects, idempotency key stability, FX hook retry/auth
cd dbt && dbt test             # 33 data tests: uniqueness, not-null, referential integrity,
                                # + 2 singular tests protecting Metric 3 from double-counting
```

## Linting

```bash
ruff check ingestion orchestration dashboard   # Python
cd dbt && sqlfluff lint models                  # SQL -- needs GCP auth (see Setup); the dbt
                                                 # templater compiles the project the same way
                                                 # `dbt build` does, ref()/source()/our
                                                 # clean_string() macro included
```

`dbt/.sqlfluff` targets the `bigquery` dialect via the `dbt` templater (not the generic `jinja` templater), so it understands this project's actual macros and `{{ ref() }}`/`{{ source() }}` calls rather than guessing at them. One rule is deliberately disabled: `structure.column_order` (ST06) wants wildcards → simple columns → calculations, but this project's convention is that grain-defining columns (stated in each mart's own "Grain: ..." header comment) lead the select list even when they're a `date()`/`coalesce()` expression — the two conflict, and the grain convention wins; see the comment in `.sqlfluff` for the specific files that motivated it.

## Orchestration (bonus)

```bash
make dagster
```

Opens the Dagster UI. The asset graph is: 4 raw ingestion assets + `fx_rates` → the full dbt staging/intermediate/marts DAG, auto-generated from the dbt manifest and linked to the raw assets via a custom `DagsterDbtTranslator` (so "the transform waits for the load" is an enforced graph dependency, not a convention). 8 asset checks cover row-count sanity and null-rate on each source's key column, plus an FX-freshness check. A daily schedule (`0 6 * * *`) simulates the "runs every morning against yesterday's data" requirement.

## CI

Every push runs `.github/workflows/ci.yml`: ruff lint, `pytest`, a sqlfluff lint of the dbt models, then a full `dbt build` against an isolated `dlight_raw_ci` / `dlight_analytics_ci` dataset pair (never touches the dev data). Auth uses Workload Identity Federation — no service-account key is stored in GitHub at all, consistent with the same key-less design used everywhere else in this repo.

## Visualization (bonus)

```bash
make dashboard   # streamlit run dashboard/streamlit_app.py — opens at localhost:8501
```

A Streamlit app reading only `dlight_analytics_marts.*` (never raw/staging). Sidebar filters for market and day; a KPI row with the provisional-window flag surfaced explicitly (turns into a warning banner the moment any disposition's 3-day payment window is still open); one tab per metric — Metric 1's coding rate by market plus the full agent/campaign coaching detail table, Metric 2's paid-post-call rate (denominator = dispositions with a contract_id, matching WRITEUP.md's headline table) alongside Metric 3's per-market local-currency value recovered, and Metric 4's inbound-driver drill-down (level 1 → 2 → 3, per the brief's ask). Markets get a fixed color across every chart in every tab — same market, same color, everywhere — and Metric 4 uses a single sequential hue rather than a categorical palette, since it's a magnitude comparison of reasons, not a set of persistent identities.
