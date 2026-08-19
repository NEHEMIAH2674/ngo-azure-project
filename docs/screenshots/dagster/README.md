# Dagster

Captured from `make dagster` (`http://localhost:3000`):

1. **`asset-graph.png`** — Jobs → `daily_pipeline`. The most information-dense shot: the full 18-asset graph (4 raw sources + `fx_rates` feeding the dbt-generated staging → intermediate → marts DAG), the job header showing the latest run succeeded, and the daily schedule (`06:00 AM UTC`, toggled on) all in one frame.
2. **`asset-graph-with-url.png`** — the same graph from the Lineage tab, kept specifically because the browser chrome (URL bar showing `127.0.0.1:3000`) is visible — proof this is a real local instance, not a staged image.
3. **`schedule.png`** — Automation tab: `daily_pipeline_schedule`, `Scheduled At 06:00 AM UTC`, toggled on.
4. **`green-run.png`** — Runs tab: run `d30c8b7e`, target `daily_pipeline`, status **Success**, duration `0:17:43`.

Both graph screenshots were captured mid-materialization (a few nodes show "Materializing…" rather than a fully settled "Materialized" timestamp) — left as-is rather than re-shot, since the job header and run list already carry the actual pass/fail proof.
