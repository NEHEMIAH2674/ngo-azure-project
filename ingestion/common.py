"""Shared helpers for the Azure ingestion scripts: config, Azure auth, logging.

Auth strategy
-------------
Uses `azure.identity.DefaultAzureCredential`, which sequentially checks:
  1. Environment variables (AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET)
  2. Azure CLI login identity (`az login`) for local development
  3. Managed Identity when deployed to Azure VMs, Web Apps, or Functions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
from typing import Any


def get_analytics_dataset() -> str:
    """Return the analytics dataset base name used by the dashboard and marts.

    Returns a schema/catalog base like `dlight_analytics` (the Streamlit app
    appends `_marts` to this where necessary).
    """
    return os.environ.get("DATABRICKS_ANALYTICS", "dlight_analytics")


def get_databricks_client() -> Any:
    """Return a lightweight Databricks SQL client adapter.

    This adapter exposes a `query(sql)` method returning an object with
    `.result()` (list[dict]) and `.to_dataframe()` (pandas.DataFrame).
    It is intentionally minimal and only implements what this repo needs.
    """
    try:
        from databricks import sql as dbsql  # type: ignore
        import pandas as pd
    except Exception as exc:  # pragma: no cover - runtime import
        raise RuntimeError("databricks-sql-connector is required to query Databricks") from exc

    class _Result:
        def __init__(self, columns, rows):
            self._cols = columns
            self._rows = rows

        def result(self):
            return [dict(zip(self._cols, r)) for r in self._rows]

        def to_dataframe(self):
            return pd.DataFrame(self.result())

    class _Client:
        def __init__(self):
            host = os.environ.get("DATABRICKS_HOST")
            http_path = os.environ.get("DATABRICKS_HTTP_PATH")
            token = os.environ.get("DATABRICKS_TOKEN")
            if not (host and http_path and token):
                raise RuntimeError("DATABRICKS_HOST/DATABRICKS_HTTP_PATH/DATABRICKS_TOKEN must be set in the environment")
            self._conn = dbsql.connect(server_hostname=host, http_path=http_path, access_token=token)

        def query(self, sql: str):
            cur = self._conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            return _Result(cols, rows)

    return _Client()

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_storage_account() -> str:
    return os.environ.get("AZURE_STORAGE_ACCOUNT", "nehemiahprojects")


def get_container_name() -> str:
    return os.environ.get("AZURE_CONTAINER_NAME", "raw-data")


def get_adls_client() -> BlobServiceClient:
    """Return an authenticated Azure BlobServiceClient instance."""
    account_name = get_storage_account()
    blob_url = f"https://{account_name}.blob.core.windows.net"
    credential = DefaultAzureCredential()
    return BlobServiceClient(account_url=blob_url, credential=credential)


def get_raw_dataset() -> str:
    """Return the raw dataset identifier for SQL operations.

    For Databricks this is returned as <catalog>.<schema>. Values are
    read from `DATABRICKS_CATALOG` and `DATABRICKS_SCHEMA` environment
    variables with sensible defaults.
    """
    catalog = os.environ.get("DATABRICKS_CATALOG", "dlight_analytics")
    schema = os.environ.get("DATABRICKS_SCHEMA", "dev_dlight_analytics")
    return f"{catalog}.{schema}"


def fq_table(dataset: str, table: str) -> str:
    """Return a fully-qualified table identifier for SQL usage.

    If `dataset` already contains a catalog portion (catalog.schema),
    this returns `catalog.schema.table`. Otherwise returns
    `dataset.table`.
    """
    if "." in dataset:
        return f"{dataset}.{table}"
    return f"{dataset}.{table}"