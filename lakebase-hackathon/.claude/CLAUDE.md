<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Databricks Lakebase Hackathon Project

Educational **Lakebase** curriculum — CLI scripts, one Databricks notebook,
and offline tests — built strictly from the spec. Single dataset: NYC Taxi + PostGIS.

- **Contract (source of truth):** `specs/lakebase-hackathon-spec.md`
- **Learning companion:** `specs/lakebase-tasks-spec.md`

## Rules
- **Spec-first:** build only what the spec specifies; do not invent modules. Read
  `specs/lakebase-hackathon-spec.md` before generating any file.
- **Build to the Deliverables section (§4); verify against the Testing & Verification section (§5).**
- **Notebook format:** native Databricks source — a `# Databricks notebook source` header,
  `# COMMAND ----------` cell delimiters, and `# MAGIC %md` for Markdown cells.
- **Beginner-first authoring (see spec §4.2):** the notebook targets readers new to Lakebase
  and Postgres internals. Title is "Lakebase Hands-On Lab" (no "Autoscaling" branding in
  title/prose). No unexplained jargon; every code cell gets a short `%md` lead-in and opens
  with a `""" … """` docstring; each module links to the official Lakebase docs.
- **License header:** every source file starts with the SPDX/copyright block.
- **Run `pytest tests/` before proposing any commit.**

## Commands
- Test: `pytest tests/`
- Format: `black .`
- Run a lab: `./scripts/NN_name.sh -p <profile>` (idempotent; `scripts/99_teardown.sh` removes all resources)

## Conventions
- **Dataset:** single `nyc_taxi` database (5-table NYC Taxi + PostGIS star schema).
- **Scripts:** accept `-p/--profile`, use `set -euo pipefail`, and are idempotent.
- **Environment:** local `.venv`; deps pinned in `requirements.txt` + `requirements-dev.txt`.
- **Docs:** `README.md` (setup & usage) · `LICENSE` (Apache-2.0).
