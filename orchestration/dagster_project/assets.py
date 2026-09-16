"""Asset definitions.

Two families of assets, wired into one graph:

1. Raw ingestion assets (one per CSV source + fx_rates) -- thin Dagster
   wrappers around the existing ingestion/ code. No logic is duplicated
   here; each asset just calls the same load_source() function / FxRates
   Operator the CLI (`make ingest`, `make fx`) uses, so there is exactly one
   implementation of "how a source gets loaded" regardless of whether it's
   invoked by hand or by Dagster.

2. The dbt asset graph, auto-generated from the dbt project's manifest via
   dagster-dbt.

The two families are linked by RawSourceDbtTranslator, which maps each dbt
*source* node (ameyo_calls, atlas_dispositions, payments, agent_mapping,
fx_rates) onto the matching raw ingestion asset's key. That is what makes
"the transform waits for the load" a real, enforced dependency in the
Dagster asset graph -- not just something documented in prose: a dbt
staging model can't materialize until its upstream raw ingestion asset has.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ingestion"))

import dagster as dg
import load_csv_to_adls
from api.fx.fx_operator import FxRatesOperator
from api.fx.hook import ExchangeRateApiHook, FxPermanentError
from common import get_adls_client
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, dbt_assets
from sources import SOURCES

from .dbt_project import dlight_dbt_project

INPUT_DIR = REPO_ROOT / "data" / "raw"


def _make_raw_ingestion_asset(source) -> dg.AssetsDefinition:
    @dg.asset(
        key=dg.AssetKey(source.name),
        group_name="ingestion",
        compute_kind="python",
        description=(
            f"Append-only landing of {source.filename} into "
            f"raw.{source.name}, gated by whole-file content hash "
            f"(see ingestion/load_csv_to_adls.py)."
        ),
    )
    def _asset(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
        # ADLS-backed raw landing: ensure manifest and upload to ADLS
        load_csv_to_adls.ensure_infra()
        adls_client = get_adls_client()
        result = load_csv_to_adls.load_source_to_adls(adls_client, source, INPUT_DIR)
        context.log.info("%s: %s", source.name, result)
        return dg.MaterializeResult(
            metadata={
                "skipped": result["skipped"],
                "rows_loaded": result.get("rows_loaded", 0),
                "rejected": result.get("rejected", 0),
                "file_name": result["file_name"],
                **({"skip_reason": result["reason"]} if result["skipped"] else {}),
            }
        )

    return _asset


raw_ingestion_assets = [_make_raw_ingestion_asset(s) for s in SOURCES]


@dg.asset(
    key=dg.AssetKey("fx_rates"),
    group_name="ingestion",
    compute_kind="python",
    deps=[dg.AssetKey("payments")],  # needs to know which payment dates require a rate
    description="Daily USD exchange rates cached from exchangerate-api.com, keyed on (rate_date, currency).",
)
def fx_rates_asset(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    try:
        hook = ExchangeRateApiHook()
    except FxPermanentError as exc:
        context.log.error("fx_rates: %s", exc)
        hook = None
    result = FxRatesOperator(hook).execute()
    context.log.info("fx_rates: %s", result)
    return dg.MaterializeResult(metadata=result)


class RawSourceDbtTranslator(DagsterDbtTranslator):
    def get_asset_key(self, dbt_resource_props):
        if dbt_resource_props.get("resource_type") == "source":
            return dg.AssetKey(dbt_resource_props["name"])
        return super().get_asset_key(dbt_resource_props)


@dbt_assets(
    manifest=dlight_dbt_project.manifest_path,
    project=dlight_dbt_project,
    dagster_dbt_translator=RawSourceDbtTranslator(),
)
def dlight_dbt_assets(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    # `dbt build` = seed + run + test in one invocation, so a model's tests
    # execute right after it materializes rather than as a separate pass --
    # a failure is attributed to the specific model/test that caused it.
    yield from dbt.cli(["build"], context=context).stream()
