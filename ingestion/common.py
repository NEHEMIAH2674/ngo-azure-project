"""Shared helpers for the ingestion scripts: config, BigQuery auth, logging.

Auth strategy
-------------
This GCP org disables service-account key export (org policy
`constraints/iam.disableServiceAccountKeyCreation`), so there is no JSON key
file anywhere in this project. Instead:

  - `google.auth.default()` loads *base* credentials the normal way (it reads
    GOOGLE_APPLICATION_CREDENTIALS if set, otherwise the machine's ADC file).
  - Those base credentials are used to *impersonate* a dedicated, narrowly
    scoped service account (BQ_IMPERSONATE_SERVICE_ACCOUNT: BigQuery Data
    Editor + Job User only) via short-lived tokens.

This means the pipeline never runs with the base identity's full permissions,
and there is no long-lived secret to leak, rotate, or accidentally commit.

In CI, GOOGLE_APPLICATION_CREDENTIALS instead points at a short-lived key
material written from a GitHub Actions secret at run time (see
.github/workflows/ci.yml) and BQ_IMPERSONATE_SERVICE_ACCOUNT is left unset,
so `google.auth.default()` alone is sufficient there.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google.auth import default as google_auth_default
from google.auth import impersonated_credentials
from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_project_id() -> str:
    return _require_env("GCP_PROJECT_ID")


def get_raw_dataset() -> str:
    # Defaults to the dev-prefixed name, deliberately: prod is the plain,
    # unmarked dataset name (dlight_raw), so an env var left unset must
    # land you in dev, never silently in prod. Only the deploy_prod CI job
    # (.github/workflows/ci.yml) explicitly overrides this to the plain
    # name -- nothing else in this repo does, or should.
    return os.environ.get("BQ_RAW_DATASET", "dev_dlight_raw")


def get_analytics_dataset() -> str:
    return os.environ.get("BQ_ANALYTICS_DATASET", "dev_dlight_analytics")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def get_bigquery_client() -> bigquery.Client:
    """Return a BigQuery client, impersonating BQ_IMPERSONATE_SERVICE_ACCOUNT
    when one is configured (local dev); using the ambient credentials as-is
    otherwise (CI, or a GCE/Cloud Run identity in a future deployment).
    """
    project = get_project_id()
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    base_credentials, _ = google_auth_default(scopes=scopes)

    impersonate_sa = os.environ.get("BQ_IMPERSONATE_SERVICE_ACCOUNT")
    if impersonate_sa:
        credentials = impersonated_credentials.Credentials(
            source_credentials=base_credentials,
            target_principal=impersonate_sa,
            target_scopes=scopes,
            lifetime=3600,
        )
    else:
        credentials = base_credentials

    return bigquery.Client(project=project, credentials=credentials)


def fq_table(dataset: str, table: str) -> str:
    """Fully-qualified `project.dataset.table` name."""
    return f"{get_project_id()}.{dataset}.{table}"
