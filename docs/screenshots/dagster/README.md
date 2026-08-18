# Dagster

Capture from `make dagster` (`http://localhost:3000`):

1. **`asset-graph.png`** — Overview → Assets, whole graph expanded: the 4 raw
   sources + `fx_rates` feeding the dbt-generated staging → intermediate →
   marts DAG as one connected graph (proves the transform genuinely depends
   on the load, not just runs after it by convention).
2. **`schedule.png`** — Overview → Schedules: `daily_pipeline_schedule`
   toggled on, cron `0 6 * * *`.
3. **`green-run.png`** — a completed run (Runs tab) showing all steps
   succeeded, including the asset checks and freshness checks passing.
