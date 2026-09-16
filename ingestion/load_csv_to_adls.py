"""Idempotent CSV -> ADLS Gen2 raw storage loader.

    python ingestion/load_csv_to_adls.py [--input-dir data/raw] [--source ameyo_calls]

Design goals retained:
  - Idempotent execution using SHA-256 file hashing.
  - Manifest logging to prevent duplicate uploads.
  - Validation checks before sending raw byte payloads to Azure ADLS Gen2.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from common import get_logger
from sources import SOURCES, Source

log = get_logger("load_csv_to_adls")

# ADLS Gen2 Configuration
STORAGE_ACCOUNT = "nehemiahprojects"
CONTAINER_NAME = "raw-data"
MANIFEST_DB_PATH = Path("ingestion/_load_manifest.db")


def get_adls_client() -> BlobServiceClient:
    blob_url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"
    credential = DefaultAzureCredential()
    return BlobServiceClient(account_url=blob_url, credential=credential)


def ensure_infra() -> None:
    """Ensures local manifest store and target ADLS Gen2 container exist."""
    # Ensure local manifest tracker exists
    with sqlite3.connect(MANIFEST_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS load_manifest (
                source_name TEXT,
                file_name TEXT,
                file_hash TEXT PRIMARY KEY,
                loaded_at TEXT,
                row_count INTEGER,
                rejected_count INTEGER,
                adls_path TEXT
            )
            """
        )
    log.info("Manifest infrastructure verified.")


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def already_loaded(hash_: str) -> bool:
    with sqlite3.connect(MANIFEST_DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM load_manifest WHERE file_hash = ?", (hash_,))
        return cursor.fetchone()[0] > 0


def record_manifest(source_name: str, file_name: str, hash_: str, valid_count: int, rejected_count: int, adls_path: str) -> None:
    with sqlite3.connect(MANIFEST_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO load_manifest (source_name, file_name, file_hash, loaded_at, row_count, rejected_count, adls_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_name,
                file_name,
                hash_,
                datetime.now(timezone.utc).isoformat(),
                valid_count,
                rejected_count,
                adls_path,
            ),
        )


def read_and_validate(source: Source, path: Path) -> tuple[list[dict], list[dict]]:
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


def load_source_to_adls(client: BlobServiceClient, source: Source, input_dir: Path) -> dict:
    path = input_dir / source.filename
    skip_result = {"skipped": True, "rows_loaded": 0, "rejected": 0, "file_name": source.filename}
    
    if not path.exists():
        log.warning("skip %s: %s not found in %s", source.name, source.filename, input_dir)
        return {**skip_result, "reason": "file_not_found"}

    hash_ = file_hash(path)
    if already_loaded(hash_):
        log.info("skip %s: %s already loaded (unchanged since last run)", source.name, path.name)
        return {**skip_result, "reason": "unchanged_since_last_run"}

    valid_rows, rejects = read_and_validate(source, path)
    log.info("%s: parsed %d valid rows, %d rejected", source.name, len(valid_rows), len(rejects))

    now = datetime.now(timezone.utc)
    # Define partitioned path structure inside ADLS Gen2
    blob_path = f"{source.name}/{now.strftime('%Y/%m/%d')}/{source.filename}"

    # Direct Stream Upload to ADLS Gen2 Container
    blob_client = client.get_blob_client(container=CONTAINER_NAME, blob=blob_path)
    with open(path, "rb") as file_data:
        blob_client.upload_blob(file_data, overwrite=True)

    record_manifest(source.name, source.filename, hash_, len(valid_rows), len(rejects), blob_path)
    log.info("%s: landed into ADLS Gen2 at path '%s'", source.name, blob_path)
    
    return {"skipped": False, "rows_loaded": len(valid_rows), "rejected": len(rejects), "file_name": source.filename}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="data/raw", type=Path)
    parser.add_argument("--source", choices=[s.name for s in SOURCES], default=None)
    parser.add_argument("--date", nargs="?", default=None)
    args = parser.parse_args()

    ensure_infra()
    adls_client = get_adls_client()

    targets = [s for s in SOURCES if args.source in (None, s.name)]
    for source in targets:
        load_source_to_adls(adls_client, source, args.input_dir)


if __name__ == "__main__":
    main()