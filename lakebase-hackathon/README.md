<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Lakebase Lab

A hands-on, spec-driven curriculum for **Databricks Lakebase** (Neon-derived,
copy-on-write Postgres managed in the Databricks control plane). It covers project
creation, short-lived OAuth credential connection pooling, copy-on-write branching, and
Point-in-Time Recovery (PITR) — all on a single **NYC Taxi + PostGIS** dataset that also
proves Lakebase is 100% standard Postgres.

> **License:** Apache-2.0

## Contents

```
lakebase-hackathon/
├── .claude/CLAUDE.md                    # Claude Code workspace directives (spec-first)
├── specs/
│   ├── lakebase-hackathon-spec.md       # Formal spec: deliverables & acceptance criteria
│   └── lakebase-tasks-spec.md           # Hands-on learning companion (module walkthroughs)
├── notebooks/
│   ├── lakebase_lab.py            # Interactive Databricks notebook (Modules 0–5)
│   └── lakebase_conn.py                 # Importable token-refresh connection manager
├── scripts/
│   ├── 00_setup_env.sh                  # Verify CLI/auth/psql/jq
│   ├── 01_create_and_connect.sh         # Provision project + init nyc_taxi dataset
│   ├── 02_branch_and_migrate.sh         # Branch, apply isolated migration, prove isolation
│   ├── 03_point_in_time_recovery.sh     # Simulate data loss + recover via PITR branch
│   └── 99_teardown.sh                   # Delete all lab resources
├── tests/
│   ├── test_cli_scripts.py              # Offline structural checks of the shell scripts
│   └── test_notebook_logic.py           # Offline tests of the token-refresh manager
├── requirements.txt                     # Runtime deps (notebook / connection manager)
├── requirements-dev.txt                 # Dev/test deps (pytest, black)
├── LICENSE                              # Apache License 2.0
└── README.md
```

## The dataset (NYC Taxi + PostGIS)

A 5-table star schema in the `nyc_taxi` database:

| Table | Role | PostGIS |
|-------|------|---------|
| `taxi_zones` | spatial dimension (TLC zones) | `geom geometry(MultiPolygon, 4326)` + GIST |
| `trips` | fact table (fares, times) | `pickup_point` / `dropoff_point geometry(Point, 4326)` + GIST |
| `vendors`, `rate_codes`, `payment_types` | lookup dimensions | — |

## Prerequisites

Two independent tracks cover the same concepts — pick one and install only its deps.

**Common (both tracks)**
- A **serverless-enabled** Databricks workspace + authenticated CLI profile

**CLI track** (`scripts/*.sh`)
- **Databricks CLI** ≥ 0.285.0 (`databricks postgres` API) — verified: 0.299.1
- **psql** (v16 recommended): `brew install postgresql@16`
- **jq**: `brew install jq`

**Notebook track** (`notebooks/lakebase_lab.py`)
- **Databricks SDK** ≥ 0.81.0 and **Python** ≥ 3.10 with `psycopg[binary]` + `sqlalchemy`
  (provided by the Databricks serverless notebook runtime)

**Testing (either track)**
- **Python** ≥ 3.10 + `pytest` to run the offline suite

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Running the CLI labs

Each script accepts `-p/--profile` (default `DEFAULT`), uses `set -euo pipefail`, and is
idempotent. Run them in order against your workspace profile:

```bash
./scripts/00_setup_env.sh              -p <profile>   # preflight checks
./scripts/01_create_and_connect.sh     -p <profile>   # create project + init dataset
./scripts/02_branch_and_migrate.sh     -p <profile>   # branch + isolated migration
./scripts/03_point_in_time_recovery.sh -p <profile>   # PITR disaster + recovery
./scripts/99_teardown.sh               -p <profile> -y  # delete everything
```

## The notebook

**Clone this repo as a Databricks Git folder** (Workspace → Repos / Git folders) so the
notebook runs alongside its siblings — do *not* import `lakebase_lab.py` as a standalone
file. The notebook imports the token-refresh manager from `notebooks/lakebase_conn.py`, reads
the bootstrap DDL/seed from `sql/bootstrap/`, and its pyway cell applies the migrations from
`sql/migrations/` — so `lakebase_conn.py` and the whole `sql/` tree must be present in the
checkout, or it fails (missing `lakebase_conn.py` → `ModuleNotFoundError`; missing
`sql/bootstrap/` → `FileNotFoundError`; missing `sql/migrations/` → pyway finds no migrations).

Once cloned, open `notebooks/lakebase_lab.py` (standard `# COMMAND ----------` source
format) and run Modules 0–5 end-to-end.

## Testing

Offline unit tests (no workspace or network required):

```bash
pytest tests/          # structural script checks + token-refresh manager logic
black .                # format
```

## Key Lakebase facts (live-validated 2026-09-04)

- **PostGIS works** — the stock `postgis` extension (3.6.0 on PG 18) installs with plain
  `CREATE EXTENSION`; 40+ standard extensions are supported.
- **Branch creation requires an expiration** — pass `ttl`, `expire_time`, or
  `no_expiry`, or the API rejects the request.
- **`delete-project` is a soft delete** — `get-project` still resolves a deleted project
  by name during its retention window; use `list-projects` membership for existence checks.
- **No git-style branch merge** — promote the *migration* (re-apply it to `production`),
  not the branch. `reset` only refreshes a child *from* its parent (UI/Terraform only).
- **PITR = branch from the past** via `source_branch` + `source_branch_time`.

## Teardown

`99_teardown.sh` deletes every non-`production` branch and then the project (cascading to
all endpoints, databases, and data). These are billable resources — tear down when done.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
