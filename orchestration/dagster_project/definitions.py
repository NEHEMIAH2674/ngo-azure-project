"""Entry point: `dagster dev -f orchestration/dagster_project/definitions.py`
(or `make dagster`, which does the same from the repo Makefile).

Wires together:
  - 4 raw ingestion assets + fx_rates            (assets.py)
  - the full dbt staging -> intermediate -> marts graph, auto-generated
    from the dbt manifest                         (assets.py, via dagster-dbt)
  - asset checks on the raw layer                 (checks.py)
  - one job selecting the whole graph + a daily schedule, simulating "the
    pipeline runs every morning against yesterday's data" from the brief.

Because every asset in this graph is idempotent by construction (raw
ingestion is gated by file-content-hash; fx_rates upserts by (date,
currency); every dbt model is a full MERGE/rebuild, not an append), a
failed run can simply be re-triggered from the Dagster UI -- there is no
manual cleanup step and no risk of double-counting.
"""

import dagster as dg
from dagster_dbt import DbtCliResource

from .assets import dlight_dbt_assets, fx_rates_asset, raw_ingestion_assets
from .checks import raw_ingestion_checks
from .dbt_project import dlight_dbt_project

daily_pipeline_job = dg.define_asset_job(
    name="daily_pipeline",
    description="Ingest all sources, refresh FX rates, then rebuild the full dbt graph.",
    selection=dg.AssetSelection.all(),
)

daily_schedule = dg.ScheduleDefinition(
    name="daily_pipeline_schedule",
    job=daily_pipeline_job,
    # The brief: "The pipeline will run every morning against yesterday's
    # data." 6am gives the source systems' overnight batch jobs time to land
    # before we read them.
    cron_schedule="0 6 * * *",
)

defs = dg.Definitions(
    assets=[*raw_ingestion_assets, fx_rates_asset, dlight_dbt_assets],
    asset_checks=raw_ingestion_checks,
    jobs=[daily_pipeline_job],
    schedules=[daily_schedule],
    resources={
        "dbt": DbtCliResource(project_dir=dlight_dbt_project),
    },
)
