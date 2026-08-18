"""Shared handle to the dbt project living at <repo_root>/dbt.

`prepare_if_dev()` runs `dbt deps` + parses a fresh manifest automatically
whenever `dagster dev` starts, so the asset graph dagster-dbt builds always
reflects the current state of the dbt project without a separate manual
`dbt parse` step.
"""

from pathlib import Path

from dagster_dbt import DbtProject

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_PROJECT_DIR = REPO_ROOT / "dbt"

dlight_dbt_project = DbtProject(
    project_dir=DBT_PROJECT_DIR,
    profiles_dir=DBT_PROJECT_DIR,
)
dlight_dbt_project.prepare_if_dev()
