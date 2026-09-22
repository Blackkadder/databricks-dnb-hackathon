<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Technical Specification: Lakebase Lab

> **Role:** This document is the **contract** — the single source of truth for *what to
> build*. Implement to **§4 (Deliverables)**, verify against **§5 (Testing & Verification)**;
> **§6** is the definition of done. Keep sections numbered and self-contained so they can be
> referenced across sessions.
> **Companion:** the hands-on, module-by-module walkthrough lives in
> [`lakebase-tasks-spec.md`](./lakebase-tasks-spec.md).

## 1. Project Overview & Architectural Boundaries

### 1.1 Objective
Build an operational learning curriculum targeting **Databricks Lakebase** (Neon-derived, copy-on-write Postgres managed within the Databricks control plane). The deliverable contains executable CLI automation scripts and a single interactive Databricks Python notebook covering database creation, short-lived OAuth credential connection pooling, copy-on-write branching, and Point-in-Time Recovery (PITR). All modules operate on a single **NYC Taxi + PostGIS** dataset (the `nyc_taxi` database), which also proves Lakebase is 100% standard Postgres — the stock `postgis` extension, foreign keys, GIST indexes, and ordinary DDL/DML all work verbatim.

The curriculum ships **two independent tracks** — a CLI track (`scripts/*.sh`) and a notebook track (`notebooks/lakebase_lab.py`) — that cover the same concepts. Pick one and install only that track's dependencies (see **§2**).

### 1.2 In-Scope vs. Out-of-Scope
* **In-Scope (Autoscaling Tier):**
  * Resource path semantics: `projects/{project_id}/branches/{branch_id}/endpoints/{endpoint_id}`
  * Databricks CLI subcommands via `databricks postgres`
  * Databricks SDK for Python via `w.postgres`
  * Dynamic compute sizing (0.5 to 112 CU; Max CU - Min CU ≤ 8 CU)
  * Scale-to-zero compute management
  * 1-hour short-lived OAuth tokens and background refresh strategies
* **Out-of-Scope (Provisioned / Legacy Tier):**
  * `databricks database` CLI and `w.database` SDK modules
  * Fixed-capacity CUs (`CU_1`, `CU_2`, `CU_4`, `CU_8`)
  * Synchronous legacy instance provisioning APIs

---

## 2. Environment Constraints & Prerequisites

The curriculum has **two independent tracks** — pick one; install only its dependencies.

* **Common (both tracks):**
  * **Workspace:** Databricks serverless-enabled workspace

* **CLI track** (`scripts/*.sh`):
  * **Databricks CLI:** `>= 0.285.0` (required for `databricks postgres` support)
  * **PostgreSQL Client:** `psql` (v16 recommended)
  * **`jq`:** for parsing CLI JSON output

* **Notebook track** (`notebooks/lakebase_lab.py`):
  * **Databricks SDK:** `>= 0.81.0` (`w.postgres` module)
  * **Python Runtime:** `>= 3.10` with `psycopg[binary]>=3.0` and `sqlalchemy>=2.0`
    (already provided by the Databricks serverless notebook runtime)

* **Testing (§5), either track:** Python `>= 3.10` + `pytest` to run the offline suite.

---

## 3. Required Repository Structure

```text
lakebase-curriculum/
├── .claude/
│   └── CLAUDE.md                    # Claude Code workspace directives
├── specs/
│   ├── lakebase-hackathon-spec.md   # Formal spec (this file): deliverables & acceptance
│   └── lakebase-tasks-spec.md       # Hands-on learning companion (module walkthroughs)
├── notebooks/
│   ├── lakebase_lab.py        # Single Databricks Python notebook
│   └── lakebase_conn.py             # Importable helpers (token refresh, derive_project_id)
├── scripts/
│   ├── 00_setup_env.sh              # Dependency & CLI verification
│   ├── 01_create_and_connect.sh     # Project provisioning + bootstrap SQL via CLI
│   ├── 02_branch_and_migrate.sh     # Branch creation, endpoint setup, migration
│   ├── 03_point_in_time_recovery.sh # Disaster simulation & PITR restoration
│   └── 99_teardown.sh               # Delete the per-user project & its branches
├── sql/                             # Version-controlled SQL — the single source of truth
│   ├── bootstrap/                   # original DDLs that build the nyc_taxi dataset
│   │   ├── 01_schema.sql            # CREATE EXTENSION postgis + 5-table star schema + GIST indexes
│   │   └── 02_seed.sql              # lookup dimensions, sample zones, sample trips
│   └── migrations/                  # branch-demo versioned migrations (pyway V*.sql)
│       ├── V01_01__add_congestion_surcharge.sql
│       └── V01_02__backfill_manhattan_surcharge.sql
├── tests/
│   ├── test_cli_scripts.py          # Shell script argument & execution tests
│   └── test_notebook_logic.py       # Offline mock tests for SDK & connection pool
└── README.md
```

**SQL is checked in under `sql/`.** The bootstrap DDL/seed (`sql/bootstrap/`) and the branch-demo versioned migrations (`sql/migrations/`, pyway `V*.sql`) are checked-in `.sql` files, reviewable and reusable across both tracks. The bootstrap DDL/seed are **read from those files** by the notebook (Module 1) and `scripts/01_create_and_connect.sh`. The Module 2 branch migration is shown **inline** in the notebook and `scripts/02_branch_and_migrate.sh` (so the learner sees the exact `ALTER`/`UPDATE` in context) *and* is provided as the checked-in `sql/migrations/` files, which the notebook's **pyway** promotion cell applies from there. If you change the migration, update both the inline demo and the `sql/migrations/` files so they stay in sync.

---

## 4. Deliverable Specifications and Functional Requirements

### 4.1 Shell Scripts (`scripts/*.sh`)

All bash scripts must:
1. Accept an optional `-p` or `--profile` argument for the Databricks CLI profile (defaulting to `DEFAULT`).
2. Execute with strict error settings (`set -euo pipefail`).
3. Output clear, readable execution logs using `jq` parsing.
4. Derive a **per-user project id** (see [§4.3](#43-naming--multi-tenancy)) instead of hardcoding a name, so many users share one workspace without collision. Each script computes `PROJECT_ID="lakebase-lab-<slug>-<numeric-user-id>"` from `databricks current-user me` and references `${PROJECT_ID}` / `${PROD_BRANCH}` thereafter.

#### Script Requirements:
* **`scripts/00_setup_env.sh`**
  * Verify `databricks --version` is ≥ 0.285.0.
  * Validate workspace authentication status using `databricks auth describe`.
  * Verify presence of `psql` client.

* **`scripts/01_create_and_connect.sh`**
  * Provision the per-user project (`${PROJECT_ID}`, see [§4.3](#43-naming--multi-tenancy)) using Postgres 18:
    ```bash
    databricks postgres create-project "${PROJECT_ID}" \
      --json '{"spec": {"display_name": "Lakebase Lab", "pg_version": "18"}}'
    ```
  * Poll until branch `production` is `READY` and endpoint `primary` is `ACTIVE`.
  * Generate short-lived OAuth credential:
    ```bash
    TOKEN=$(databricks postgres generate-database-credential \
      "${PROD_BRANCH}/endpoints/primary" -o json | jq -r '.token')
    ```
  * Initialize the **`nyc_taxi`** dataset by piping the checked-in bootstrap SQL through `psql` (using `$TOKEN` as the password): first `sql/bootstrap/01_schema.sql` (create the database, `CREATE EXTENSION IF NOT EXISTS postgis`, the 5-table star schema — `taxi_zones` with a `MultiPolygon` geometry + GIST index; `vendors`, `rate_codes`, `payment_types` lookups; `trips` fact table with pickup/dropoff `Point` geometries, FKs to every dimension, and GIST indexes), then `sql/bootstrap/02_seed.sql` (lookups, a few zones, sample trips). The SQL is not inlined in the script. Full annotated DDL/seed also appears in `specs/lakebase-tasks-spec.md` §1d.

* **`scripts/02_branch_and_migrate.sh`**
  * Create branch `feature-x` from `production` with a 7-day TTL (`604800s`):
    ```bash
    databricks postgres create-branch "${PROJECT_ID}" feature-x \
      --json "{\"spec\": {\"source_branch\": \"${PROD_BRANCH}\", \"ttl\": \"604800s\"}}"
    ```
  * Attach read-write endpoint with autoscaling (Min: 0.5 CU, Max: 2.0 CU):
    ```bash
    databricks postgres create-endpoint "${FBRANCH}" primary \
      --json '{"spec": {"endpoint_type": "ENDPOINT_TYPE_READ_WRITE", "autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 2.0}}'
    ```
  * Apply a schema migration on `feature-x` (`ALTER TABLE trips ADD COLUMN congestion_surcharge NUMERIC(8,2) DEFAULT 0;`), backfill Manhattan-pickup trips, and log successful **isolated** execution — the column is present on `feature-x` and absent on `production`. (Promotion = re-applying the same migration to `production`; there is no git-style branch merge.)

* **`scripts/03_point_in_time_recovery.sh`**
  * Capture pre-corruption timestamp $T_0$ via `date -u +"%Y-%m-%dT%H:%M:%SZ"`.
  * Simulate accidental data loss ($T_1$) by running `DROP TABLE trips;` on production.
  * Create a new branch `recovery-branch` sourced from `production` at $T_0$ using the point-in-time branch spec (`source_branch` + `source_branch_time`). Note: branch creation **requires an expiration** — include `ttl` (or `expire_time` / `no_expiry`) or the API rejects the request.
  * Generate an endpoint on `recovery-branch` and execute `SELECT count(*) FROM trips;` via `psql` to verify data recovery.

---

### 4.2 Interactive Databricks Notebook (`notebooks/lakebase_lab.py`)

The notebook must be stored in the native Databricks source format: a `# Databricks notebook source` header, `# COMMAND ----------` cell delimiters, and `# MAGIC %md` for Markdown cells (the format used by `databricks workspace import/export`).

#### Authoring conventions (beginner-first)

The notebook is written for readers **new to Lakebase and new to PostgreSQL internals**. It must therefore:

* **Title:** open with an H1 Markdown title **"Lakebase Hands-On Lab"** and a one-line subtitle. Do **not** use "Autoscaling" as a product-name qualifier in the title or narrative prose. (The elastic-compute *capability* — compute scaling between a min/max and down to zero when idle — is still taught in Module 4, described in plain terms.)
* **No unexplained jargon:** any low-level term (e.g., WAL, page, pageserver, safekeeper) is either defined in one plain-English clause on first use, or avoided. Prefer analogies over internals.
* **Markdown lead-in before every code cell:** each code cell is immediately preceded by a short (≈2–4 sentence) `# MAGIC %md` cell that says, in plain English, what the step does and what to look for in the output. Module-level intro cells remain, but *every* code cell also gets its own lead-in.
* **Self-documenting code:** each code cell opens with a triple-quoted `""" … """` docstring restating its purpose, plus inline comments on any non-obvious line.
* **Docs links:** each module's lead Markdown links to the relevant official Lakebase documentation (`docs.databricks.com/aws/en/oltp/…`).

#### Modules

The notebook opens with an unnumbered **"What is Lakebase?"** overview, then six numbered modules (0–5).

* **Intro — What is Lakebase? (architecture in plain English)**
  * *Doc Cell (`# MAGIC %md`):* Explain — without unexplained jargon — that Lakebase is fully-managed PostgreSQL where **storage and compute are separate** and **storage keeps its history** (analogy: version history / undo for the database). From that single idea, explain in plain terms why compute can **scale to zero** when idle, and why **branches** (instant copies) and **point-in-time recovery** are the *same* cheap mechanism — no data is copied and no logs are replayed. Show the resource layout (`Project → Branch → Endpoint`; inside a branch, `Database → Schema`). Link to the Lakebase overview / architecture docs.
* **Module 0: Connect to Databricks & Sign In**
  * *Code:* Instantiate `WorkspaceClient()`, read the signed-in identity (`w.current_user.me()`), derive the per-user `PROJECT_ID` (see [§4.3](#43-naming--multi-tenancy)), and define the resource names reused throughout (`PROJECT`, `PROD_BRANCH`, `DATABASE = "nyc_taxi"`).
* **Module 1: Create a Database & Log In (for absolute beginners)**
  * *Doc Cell (`# MAGIC %md`):* Explain the authentication model from scratch: **who you are** (your Databricks identity is the Postgres username), **how you log in** (generate a short-lived credential — an OAuth token that expires after **1 hour** — and use it as the Postgres password over a required SSL connection), and the **connection limits** (24-hour idle timeout, 3-day maximum connection life, and a brief scale-to-zero wake latency on the first connect after idle). Note the native-Postgres-password option for tools that cannot rotate tokens hourly. Link to the Lakebase authentication + connect docs.
  * *Code:* Create the per-user project via `w.postgres.create_project().wait()` (idempotent — reuse if it already exists).
  * *Code:* Initialize the `nyc_taxi` dataset by executing the checked-in `sql/bootstrap/01_schema.sql` (enable `postgis`, create the 5-table star schema) and `sql/bootstrap/02_seed.sql` (read the files, don't inline the SQL), then perform standard CRUD — including PostGIS spatial reads (`ST_Contains`, `ST_DistanceSphere`) — against `trips`.
  * *Code:* Implement a resilient SQLAlchemy engine with a `do_connect` event listener that refreshes the credential when the token exceeds 50 minutes of age (the production long-lived-pool pattern).
* **Module 2: Copy-on-Write Branching Workflow**
  * *Doc Cell (`# MAGIC %md`):* Explain fast copy-on-write branching in plain terms (an instant, effectively free clone that shares the parent's storage until something changes) and highlight the absence of a Git-style automatic merge — you promote the *migration*, not the branch. Link to the Branches docs.
  * *Code:* Programmatically branch `feature-x` using `w.postgres.create_branch()`, provision an endpoint, apply the isolated migration (`ALTER TABLE trips ADD COLUMN congestion_surcharge …` + Manhattan backfill), confirm it's absent on `production`, then promote by re-applying the same migration to `production`.
  * *Doc Cell (`# MAGIC %md`):* Explain and demonstrate an alternative, production-grade way to promote a branch change to production using **pyway** (a pip-installable Python port of Flyway) to handle versioned upgrades — numbered `V*.sql` files applied in order via a tracked history table. Link to the pyway repo (https://github.com/jasondcamp/pyway).
  * *Code:* Programmatically demo pyway — install it in the top `%pip` cell (to avoid a mid-notebook restart), point `PYWAY_DATABASE_MIGRATION_DIR` at the checked-in `sql/migrations/` folder and the other `PYWAY_*` env vars at the production branch, then run `pyway info` / `pyway migrate`.
* **Module 3: Point-in-Time Recovery (PITR)**
  * *Doc Cell (`# MAGIC %md`):* Explain in plain English that recovery is "branch from the past" — because storage keeps its history, you create a branch as of an earlier timestamp; there is no separate restore step and no log replay. Link to the instant-restore docs.
  * *Code:* Capture $T_0$, execute `DELETE FROM trips;`, branch from $T_0$ via `source_branch_time`, attach endpoint, and validate recovered rows.
* **Module 4: Administration & Operations Summary**
  * *Doc Cell (`# MAGIC %md`):* Document, in plain terms, elastic compute scaling (min/max CU, scales down to zero when idle; range 0.5–112 CU at 2 GB RAM/CU; max − min ≤ 8 CU), read replicas, Unity Catalog foreign catalog registration (`CREATE FOREIGN CATALOG`), the Data API (PostgREST), and the cost model ($0.111/CU-hr compute, $0.35/GB-mo storage, $0.20/GB-mo PITR). Link to the autoscaling / scale-to-zero / read-replicas docs.
* **Module 5: Clean Up (Teardown)**
  * *Doc Cell (`# MAGIC %md`):* Explain that Lakebase bills for compute (near zero when idle) and storage, so removing lab resources when finished is good hygiene. Mirror `scripts/99_teardown.sh`: delete non-`production` branches first (children before parent), then the project (cascades to production, endpoints, databases, and data). Note `delete_project` is a *soft* delete (drops from `list_projects` but may still resolve by name during retention).
  * *Code:* Guarded by a `CONFIRM_TEARDOWN` flag (default `False`) and idempotent (`allow_missing=True` + list-based skip): iterate `w.postgres.list_branches()` deleting each non-production branch via `w.postgres.delete_branch().wait()`, then `w.postgres.delete_project().wait()`.

---

### 4.3 Naming & Multi-Tenancy

This curriculum is run by **many users sharing one workspace** (a hackathon with potentially thousands of participants), so resource names must not collide. Only the **project** name occupies a shared namespace — everything nested inside a project (the `production` / `feature-x` / `recovery-branch` branches, the `nyc_taxi` database, and the endpoints) is per-user isolated and never collides. Therefore **only the project id is made unique per user**.

* **Derived project id:** `PROJECT_ID = "lakebase-lab-<slug>-<numeric-user-id>"`, where:
  * `<numeric-user-id>` is the Databricks user id (`w.current_user.me().id`, or `databricks current-user me | jq -r .id`). It **guarantees** uniqueness within the workspace — it is the platform's unique id, **not a hash**, so there is no collision probability even at thousands of users.
  * `<slug>` is the sanitized email local-part (lowercase; runs of non-alphanumerics → `-`; trimmed; truncated to ≤ 20 chars; falls back to `user` if empty). It exists for human readability only and never affects uniqueness.
* **Single source of truth:** the derivation is a pure, offline-unit-tested function `derive_project_id(user_id, user_name)` in `notebooks/lakebase_conn.py`. The notebook imports it; each shell script reproduces the identical rule from `databricks current-user me`.
* **Fixed names:** `DATABASE = "nyc_taxi"` and all branch names stay literal — they live inside the per-user project, so they need no suffix.

---

## 5. Testing & Verification Suite (`tests/`)

### 5.1 CLI Script Validation (`tests/test_cli_scripts.py`)
* Use `pytest` to assert that all target scripts (`scripts/00_setup_env.sh` through `03_point_in_time_recovery.sh`) exist on disk.
* Check file permissions to verify execution flag (`chmod +x`).
* Parse shell script text content to enforce:
  * Presence of strict mode (`set -euo pipefail`).
  * Support for `--profile` / `-p` flag evaluation.
  * Prohibition of legacy provisioned commands (`databricks database`).

### 5.2 Python Logic & SDK Mocking (`tests/test_notebook_logic.py`)
* Use `pytest` and `unittest.mock` to test the token-refresh connection manager without making live calls to Databricks.
* Mock `WorkspaceClient.postgres.generate_database_credential()` to return synthetic short-lived tokens.
* Verify that the SQLAlchemy `do_connect` listener detects token age > 50 minutes and calls the credential generator prior to opening a connection.
* Verify `derive_project_id` (§4.3): deterministic output, sanitized/truncated slug, the `user`-fallback for an empty local-part, and that two users whose slugs coincide still get distinct project ids (uniqueness carried by the numeric user id).

---

## 6. Acceptance Criteria & Definition of Done

1. **Environment Setup:** `scripts/00_setup_env.sh` runs cleanly and validates CLI version ≥ 0.285.0.
2. **CLI Infrastructure Pipeline:** `scripts/01` through `scripts/03` execute sequentially against a live workspace profile and produce expected `jq` status outputs (`READY`, `ACTIVE`).
3. **Notebook Execution:** `notebooks/lakebase_lab.py` imports directly into Databricks and runs end-to-end without credential expiration failures.
4. **Offline Testing:** Running `pytest tests/` passes 100% of CLI structural and Python connection manager unit tests without requiring active network connectivity.