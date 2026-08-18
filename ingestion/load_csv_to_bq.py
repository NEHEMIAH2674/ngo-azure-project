"""Idempotent CSV -> BigQuery raw loader.

    python ingestion/load_csv_to_bq.py [--input-dir data/raw] [--source ameyo_calls]

Design goals (from the brief):
  - "Load the four extracts into your warehouse through code/tool, not by
    hand" -> this script, run via `make ingest`.
  - "We should be able to delete your tables, run one command, and get them
    back" -> `ensure_infra()` recreates dataset/tables from the schema in
    sources.py if they don't exist; nothing here depends on manual setup.
  - "Assume tomorrow there is another day of files. Your loader should
    handle that without you editing it" -> a `_load_manifest` table records
    (source, file content hash) pairs already ingested. Dropping a new day's
    file in --input-dir with the same canonical name and re-running loads
    only what's new; re-running on an unchanged file is a no-op.
  - Malformed rows (wrong field count once properly CSV-parsed) never crash
    the load or vanish silently: they're excluded from the batch that gets
    loaded and logged individually (source file, line number, reason), plus
    counted in `_load_manifest.rejected_count`. Across all four real extracts
    this count is 0.
  - Raw is raw, byte-for-byte: every business column lands as the literal
    STRING value parsed from the CSV -- no casting, no trimming, no
    "" -> NULL conversion, and (see below) NO row-level deduplication.

Idempotency strategy: file-level, not row-level
--------------------------------------------------
Idempotency here is enforced by content hash at the FILE level only:
`_load_manifest` records a SHA-256 of every file that's been loaded, and a
file whose hash is already present is skipped entirely. Re-running the
loader on an unchanged extract is therefore always a safe no-op.

Loading is a plain WRITE_APPEND -- there is deliberately no MERGE/upsert by
natural key at this layer. Three of the four sources do have an evident
natural key (ch_call_id, call_log_id, (contact_centre, ameyo_user_id)), and
an earlier version of this loader MERGE-upserted on it. That turned out to
be the wrong call for two reasons found by profiling the real extracts:

  1. It's a correctness trap. BigQuery's MERGE allows multiple unmatched
     source rows sharing a key to all insert on a first load, but raises
     "UPDATE/MERGE must match at most one source row for each target row"
     the moment a *second* file re-touches that key -- i.e. it can work
     today and hard-crash tomorrow on a perfectly realistic input (verified
     directly against BigQuery, not from memory).
  2. It's the wrong layer for the decision. Atlas Ameyo Mapping.csv has 29
     agent keys with genuinely conflicting duplicate rows (different team,
     different atlas_user_name) and no timestamp anywhere to say which is
     current. Silently upserting to "whichever loaded last" at the raw
     layer would destroy that evidence before anyone -- including us --
     gets to see and reason about it. Raw is supposed to be what arrived.

So raw.* is an append-only landing log: every physical row from every
distinct file ever loaded is present, including exact duplicates and
unresolved conflicts. Picking one canonical row per business key is a
transformation decision -- it happens explicitly, with a documented rule,
in dbt staging (see dbt/models/staging/), where it's also covered by tests.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from common import fq_table, get_analytics_dataset, get_bigquery_client, get_logger, get_project_id, get_raw_dataset
from google.cloud import bigquery
from sources import SOURCES, Source

log = get_logger("load_csv_to_bq")

METADATA_SCHEMA = [
    bigquery.SchemaField("_source_file", "STRING"),
    bigquery.SchemaField("_ingested_at", "TIMESTAMP"),
]

MANIFEST_SCHEMA = [
    bigquery.SchemaField("source_name", "STRING"),
    bigquery.SchemaField("file_name", "STRING"),
    bigquery.SchemaField("file_hash", "STRING"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
    bigquery.SchemaField("row_count", "INT64"),
    bigquery.SchemaField("rejected_count", "INT64"),
]


def full_schema(source: Source) -> list[bigquery.SchemaField]:
    return [*source.schema, *METADATA_SCHEMA]


def ensure_infra(client: bigquery.Client) -> None:
    project = get_project_id()
    for dataset in (get_raw_dataset(), get_analytics_dataset()):
        client.create_dataset(bigquery.Dataset(f"{project}.{dataset}"), exists_ok=True)

    for source in SOURCES:
        table = bigquery.Table(fq_table(get_raw_dataset(), source.name), schema=full_schema(source))
        client.create_table(table, exists_ok=True)
    manifest_table = bigquery.Table(fq_table(get_raw_dataset(), "_load_manifest"), schema=MANIFEST_SCHEMA)
    client.create_table(manifest_table, exists_ok=True)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def already_loaded(client: bigquery.Client, source_name: str, hash_: str) -> bool:
    query = f"""
        SELECT COUNT(*) AS n FROM `{fq_table(get_raw_dataset(), "_load_manifest")}`
        WHERE source_name = @source_name AND file_hash = @file_hash
    """
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("source_name", "STRING", source_name),
                bigquery.ScalarQueryParameter("file_hash", "STRING", hash_),
            ]
        ),
    )
    return next(iter(job.result()))["n"] > 0


def read_and_validate(source: Source, path: Path) -> tuple[list[dict], list[dict]]:
    """Parse the CSV with no reinterpretation of values: whatever string sat
    between the commas (after correct CSV de-quoting, which is required just
    to split the file into fields/rows at all) is what gets loaded. Empty
    cells stay empty strings; nothing is cast, trimmed, or deduplicated here.
    """
    valid_rows: list[dict] = []
    rejects: list[dict] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = [h.strip().strip('"') for h in next(reader)]
        if header != source.columns:
            raise ValueError(f"{path}: header {header} does not match expected {source.columns}")

        for line_no, raw_row in enumerate(reader, start=2):
            if len(raw_row) != len(source.columns):
                rejects.append(
                    {
                        "line_number": line_no,
                        "raw_line": ",".join(raw_row),
                        "reason": f"expected {len(source.columns)} fields, got {len(raw_row)}",
                    }
                )
                continue
            row = dict(zip(source.columns, raw_row))
            row = source.transform_row(row)
            valid_rows.append(row)
    return valid_rows, rejects


def load_source(client: bigquery.Client, source: Source, input_dir: Path) -> dict:
    """Load one source's CSV into raw.*. Returns a small status dict so
    callers (the CLI, and the Dagster asset in orchestration/) can report
    what happened without re-deriving it: {skipped, rows_loaded, rejected,
    file_name}.
    """
    path = input_dir / source.filename
    skip_result = {"skipped": True, "rows_loaded": 0, "rejected": 0, "file_name": source.filename}
    if not path.exists():
        log.warning("skip %s: %s not found in %s", source.name, source.filename, input_dir)
        return {**skip_result, "reason": "file_not_found"}

    hash_ = file_hash(path)
    if already_loaded(client, source.name, hash_):
        log.info("skip %s: %s already loaded (unchanged since last run)", source.name, path.name)
        return {**skip_result, "reason": "unchanged_since_last_run"}

    valid_rows, rejects = read_and_validate(source, path)
    log.info("%s: parsed %d valid rows, %d rejected", source.name, len(valid_rows), len(rejects))

    now = datetime.now(timezone.utc).isoformat()
    for row in valid_rows:
        row["_source_file"] = source.filename
        row["_ingested_at"] = now

    if valid_rows:
        job_config = bigquery.LoadJobConfig(
            schema=full_schema(source),
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        )
        target = fq_table(get_raw_dataset(), source.name)
        client.load_table_from_json(valid_rows, target, job_config=job_config).result()

    for r in rejects:
        log.warning(
            "%s: rejected line %d in %s (%s): %r",
            source.name, r["line_number"], source.filename, r["reason"], r["raw_line"][:200],
        )

    client.insert_rows_json(
        fq_table(get_raw_dataset(), "_load_manifest"),
        [
            {
                "source_name": source.name,
                "file_name": source.filename,
                "file_hash": hash_,
                "loaded_at": now,
                "row_count": len(valid_rows),
                "rejected_count": len(rejects),
            }
        ],
    )
    log.info("%s: appended %d rows into raw.%s", source.name, len(valid_rows), source.name)
    return {"skipped": False, "rows_loaded": len(valid_rows), "rejected": len(rejects), "file_name": source.filename}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="data/raw", type=Path)
    parser.add_argument("--source", choices=[s.name for s in SOURCES], default=None,
                         help="Load a single source; default loads all four.")
    # Accepted for symmetry with `make ingest DATE=...`; the loader itself
    # is date-agnostic (see module docstring) but this makes intent explicit
    # in logs and orchestration. nargs="?" is required, not cosmetic: the
    # Makefile's `ingest:` target always passes `--date $(DATE)`, and DATE
    # has no default, so bare `make ingest` expands to a literal trailing
    # `--date` with nothing after it. Without nargs="?", argparse treats
    # that as a missing required value and exits before ensure_infra() ever
    # runs -- silently breaking the "delete your tables, run one command,
    # get them back" promise for the exact invocation the README documents.
    parser.add_argument("--date", nargs="?", default=None)
    args = parser.parse_args()

    client = get_bigquery_client()
    ensure_infra(client)

    targets = [s for s in SOURCES if args.source in (None, s.name)]
    for source in targets:
        load_source(client, source, args.input_dir)


if __name__ == "__main__":
    main()
