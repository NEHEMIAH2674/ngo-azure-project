"""Entry point: `dagster dev -f orchestration/dagster_project/definitions.py`
(or `make dagster`, which does the same from the repo Makefile).

Wires together:
  - 4 raw ingestion assets + fx_rates            (assets.py)
  - the full dbt staging -> intermediate -> marts graph, auto-generated
    from the dbt manifest                         (assets.py, via dagster-dbt)
  - asset checks on the raw layer                 (checks.py)
  - freshness checks on the raw layer and the consumer-facing marts,
    tied to the same daily schedule                (freshness.py)
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
from .freshness import freshness_checks

# max_concurrent=1: the default multiprocess executor spawns a fresh
# subprocess per step, and each one re-imports this whole module -- which
# re-triggers dlight_dbt_project.prepare_if_dev() (dbt deps + dbt parse) as
# an import-time side effect. The 4 raw ingestion assets have no
# interdependencies, so with unlimited concurrency they all launch at once
# and race on the same dbt_packages/ directory: one subprocess's dbt deps
# reinstall transiently empties it while a sibling's dbt parse reads it,
# and the step fails with "0 package(s) installed in dbt_packages" --
# verified directly (two consecutive runs failed this exact way; serial
# execution fixed it). This pipeline's data volume doesn't need real
# per-step parallelism, so serializing is the right trade-off here rather
# than working around dagster-dbt's dev-mode manifest preparation.
daily_pipeline_job = dg.define_asset_job(
    name="daily_pipeline",
    description="Ingest all sources, refresh FX rates, then rebuild the full dbt graph.",
    selection=dg.AssetSelection.all(),
    executor_def=dg.multiprocess_executor.configured({"max_concurrent": 1}),
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
    asset_checks=[*raw_ingestion_checks, *freshness_checks],
    jobs=[daily_pipeline_job],
    schedules=[daily_schedule],
    resources={
        "dbt": DbtCliResource(project_dir=dlight_dbt_project),
    },
)
