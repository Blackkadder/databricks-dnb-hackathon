# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Structural validation of the CLI shell scripts (spec §5.1).

These are offline checks — they parse the script *text*; they never execute the scripts
or touch a workspace.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_DIR / "scripts"
SQL_DIR = REPO_DIR / "sql"
SCRIPTS = [
    "00_setup_env.sh",
    "01_create_and_connect.sh",
    "02_branch_and_migrate.sh",
    "03_point_in_time_recovery.sh",
    "99_teardown.sh",
]

# The checked-in SQL that the notebook and scripts read (spec §3).
BOOTSTRAP_SQL = ["bootstrap/01_schema.sql", "bootstrap/02_seed.sql"]
MIGRATION_SQL = [
    "migrations/V01_01__add_congestion_surcharge.sql",
    "migrations/V01_02__backfill_manhattan_surcharge.sql",
]


def _read(name: str) -> str:
    return (SCRIPTS_DIR / name).read_text()


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_exists(name: str) -> None:
    assert (SCRIPTS_DIR / name).is_file(), f"missing script: {name}"


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_is_executable(name: str) -> None:
    mode = (SCRIPTS_DIR / name).stat().st_mode
    assert mode & stat.S_IXUSR, f"{name} is not executable (chmod +x)"


@pytest.mark.parametrize("name", SCRIPTS)
def test_strict_mode(name: str) -> None:
    assert "set -euo pipefail" in _read(name), f"{name} missing strict mode"


@pytest.mark.parametrize("name", SCRIPTS)
def test_supports_profile_flag(name: str) -> None:
    text = _read(name)
    assert "--profile" in text and "-p" in text, f"{name} must accept -p/--profile"


@pytest.mark.parametrize("name", SCRIPTS)
def test_uses_autoscaling_api_only(name: str) -> None:
    # The legacy Provisioned tier ("databricks database") is out of scope.
    assert "databricks database" not in _read(
        name
    ), f"{name} uses the legacy Provisioned CLI"


@pytest.mark.parametrize("name", SCRIPTS)
def test_has_bash_shebang(name: str) -> None:
    assert _read(name).startswith("#!"), f"{name} missing shebang"


# --- checked-in SQL (spec §3): files exist and scripts read them, not inline it --------


@pytest.mark.parametrize("rel", BOOTSTRAP_SQL + MIGRATION_SQL)
def test_sql_file_exists(rel: str) -> None:
    assert (SQL_DIR / rel).is_file(), f"missing SQL file: sql/{rel}"


@pytest.mark.parametrize("rel", MIGRATION_SQL)
def test_migration_follows_pyway_naming(rel: str) -> None:
    # pyway versioned migrations: V<major>_<minor>[_<patch>]__<description>.sql
    assert re.match(
        r"^V\d+_\d+(_\d+)?__.+\.sql$", Path(rel).name
    ), f"{rel} is not a valid pyway migration filename"


def test_script_01_reads_bootstrap_sql_not_inline() -> None:
    # The DDL/seed must come from the files, not a heredoc embedded in the script.
    text = _read("01_create_and_connect.sh")
    assert (
        "sql/bootstrap" in text or "SQL_DIR" in text
    ), "script 01 must read sql/bootstrap"
    assert "CREATE TABLE IF NOT EXISTS trips" not in text, "script 01 still inlines DDL"


def test_script_01_display_name_is_project_id() -> None:
    # The project's UI display name must be the per-user project id, not a shared literal
    # (otherwise every user's project shows the same "Lakebase Lab" name).
    text = _read("01_create_and_connect.sh")
    assert (
        '"display_name": "Lakebase Lab"' not in text
    ), "script 01 still uses the shared literal display name"
    assert "display_name" in text and "${PROJECT_ID}" in text


# --- application schema (cabs) --------------------------------------------------------


def test_bootstrap_creates_cabs_schema_with_search_path() -> None:
    # Application tables live in a dedicated `cabs` schema (not public), made the default
    # via a database-level search_path so unqualified names resolve to cabs.* everywhere.
    sql = (SQL_DIR / "bootstrap" / "01_schema.sql").read_text()
    assert "CREATE SCHEMA IF NOT EXISTS cabs" in sql, "cabs schema is not created"
    assert (
        "ALTER DATABASE nyc_taxi SET search_path = cabs, public" in sql
    ), "search_path is not persisted at the database level"


def test_script_01_checks_existence_via_list_projects() -> None:
    # delete-project is a soft delete; get-project still resolves a soft-deleted project
    # during retention, so existence must be tested via list-projects membership.
    text = _read("01_create_and_connect.sh")
    assert "list-projects" in text, "script 01 must check existence via list-projects"
    assert (
        "postgres get-project" not in text
    ), "script 01 must not invoke get-project for existence (soft-delete ghost)"


def test_pitr_script_checks_cabs_trips() -> None:
    # The PITR script's data-loss check must reference the cabs-qualified table.
    text = _read("03_point_in_time_recovery.sh")
    assert "to_regclass('cabs.trips')" in text
    assert "to_regclass('public.trips')" not in text
