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