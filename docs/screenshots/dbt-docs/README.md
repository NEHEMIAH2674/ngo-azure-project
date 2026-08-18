# dbt docs

Capture from `dbt docs generate && dbt docs serve` (`http://localhost:8080`):

1. **`lineage-graph.png`** — the full DAG view, staging → intermediate →
   marts, ideally with `fct_paid_post_call` selected so its upstream lineage
   highlights.
2. **`model-doc-page.png`** — a model's documentation page (e.g.
   `fct_paid_post_call` or `agg_daily_summary`) showing the grain
   description and column-level docs rendered from the `.yml` files, not
   just the SQL comments — proof the documentation is real dbt metadata,
   queryable and generated, not decoration.
