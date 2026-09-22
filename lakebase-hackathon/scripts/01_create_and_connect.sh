#!/usr/bin/env bash
#
# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# 01_create_and_connect.sh — Provision the Lakebase project and initialize the
# NYC Taxi + PostGIS dataset (`nyc_taxi`) on the production branch.
#
# Idempotent: safe to re-run. Uses only the `databricks postgres` API.
set -euo pipefail

PROFILE="DEFAULT"
usage() { echo "Usage: $0 [-p|--profile PROFILE]"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile) PROFILE="${2:?--profile needs a value}"; shift 2 ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

log() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
ok()  { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }

# Per-user project id — unique within the workspace (this lab has many users). Uniqueness
# is guaranteed by the numeric Databricks user id; the email slug is only for readability.
# nyc_taxi and the branch names live inside the project, so they stay fixed.
_me="$(databricks current-user me -p "$PROFILE" -o json)"
_uid="$(jq -r '.id' <<<"$_me")"
_slug="$(jq -r '.userName' <<<"$_me" | sed -E 's/@.*$//' | tr '[:upper:]' '[:lower:]' \
         | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-20 | sed -E 's/-+$//')"
[[ -n "$_uid" ]] || { echo "could not resolve Databricks user id" >&2; exit 1; }
PROJECT_ID="lakebase-lab-${_slug:-user}-${_uid}"
PROJECT="projects/${PROJECT_ID}"
PROD_BRANCH="${PROJECT}/branches/production"
DB="nyc_taxi"

# Bootstrap SQL lives under sql/ (single source of truth), resolved relative to this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL_DIR="${SCRIPT_DIR}/../sql/bootstrap"

dbx() { databricks postgres "$@" -p "$PROFILE" -o json; }

# --- 1. Create project (idempotent; create-project waits for the LRO) ---
# NOTE: delete-project is a *soft* delete, and get-project still resolves a soft-deleted
# project during retention — so it is not a reliable existence test. Check membership in
# list-projects (soft-deleted projects drop out of it) instead. If a prior teardown left a
# tombstone, create-project errors "A soft-deleted project currently has this resource
# name"; purge it once with:
#   databricks api delete "/api/2.0/postgres/projects/${PROJECT_ID}?purge=true" -p "$PROFILE"
log "Creating project ${PROJECT_ID} (Postgres 18)"
if dbx list-projects | jq -e --arg n "$PROJECT" 'any(.[]?; .name == $n)' >/dev/null; then
  ok "project already exists"
else
  databricks postgres create-project "$PROJECT_ID" -p "$PROFILE" \
    --json "{\"spec\": {\"display_name\": \"${PROJECT_ID}\", \"pg_version\": \"18\"}}" >/dev/null
  ok "project created"
fi

# --- 2. Wait for the production branch to reach READY ---
log "Waiting for branch 'production' to reach READY"
state=""
for _ in $(seq 1 60); do
  state="$(dbx list-branches "$PROJECT" \
    | jq -r '.[] | select(.name|endswith("/branches/production")) | .status.current_state')"
  echo "    branch state: ${state:-<none>}"
  [[ "$state" == "READY" ]] && break
  sleep 5
done
[[ "$state" == "READY" ]] || { echo "branch 'production' never became READY" >&2; exit 1; }
ok "branch production READY"

# --- 3. Discover + wait for the primary endpoint (ACTIVE or IDLE) ---
log "Waiting for the production endpoint"
EP_NAME=""
for _ in $(seq 1 60); do
  EP_NAME="$(dbx list-endpoints "$PROD_BRANCH" | jq -r '.[0].name // empty')"
  [[ -n "$EP_NAME" ]] && break
  sleep 3
done
[[ -n "$EP_NAME" ]] || { echo "no endpoint found on production" >&2; exit 1; }
state=""
for _ in $(seq 1 60); do
  state="$(dbx get-endpoint "$EP_NAME" | jq -r '.status.current_state')"
  echo "    endpoint state: ${state:-<none>}"
  [[ "$state" == "ACTIVE" || "$state" == "IDLE" ]] && break
  sleep 5
done
[[ "$state" == "ACTIVE" || "$state" == "IDLE" ]] || { echo "endpoint never became ready" >&2; exit 1; }
ok "endpoint ${EP_NAME##*/} is ${state}"

# --- 4. Connection details (host, 1-hour OAuth token, identity) ---
log "Fetching host, OAuth token, and identity"
HOST="$(dbx get-endpoint "$EP_NAME" | jq -r '.status.hosts.host')"
TOKEN="$(dbx generate-database-credential "$EP_NAME" | jq -r '.token')"
EMAIL="$(databricks current-user me -p "$PROFILE" -o json | jq -r '.userName')"
[[ -n "$HOST" && -n "$TOKEN" && -n "$EMAIL" ]] || { echo "missing connection details" >&2; exit 1; }
ok "host=${HOST}"
ok "user=${EMAIL}"

export PGPASSWORD="$TOKEN"
PG_POSTGRES="host=${HOST} port=5432 dbname=postgres user=${EMAIL} sslmode=require"
PG_NYC="host=${HOST} port=5432 dbname=${DB} user=${EMAIL} sslmode=require"

# --- 5. Create database (idempotent) ---
log "Creating database ${DB}"
if psql "$PG_POSTGRES" -tAc "SELECT 1 FROM pg_database WHERE datname='${DB}'" | grep -q 1; then
  ok "database ${DB} already exists"
else
  psql "$PG_POSTGRES" -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${DB};"
  ok "database ${DB} created"
fi

# --- 6. Schema: PostGIS + 5-table star schema (idempotent) ---
log "Applying schema from sql/bootstrap/01_schema.sql"
psql "$PG_NYC" -v ON_ERROR_STOP=1 -f "${SQL_DIR}/01_schema.sql"
ok "schema applied"

# --- 7. Seed data (deterministic: upsert lookups/zones, reset+load trips) ---
log "Seeding from sql/bootstrap/02_seed.sql"
psql "$PG_NYC" -v ON_ERROR_STOP=1 -f "${SQL_DIR}/02_seed.sql"
ok "seed complete"

# --- 8. Smoke test ---
log "Verifying (PostGIS enabled + row count)"
psql "$PG_NYC" -v ON_ERROR_STOP=1 -c "SELECT postgis_full_version();"
psql "$PG_NYC" -v ON_ERROR_STOP=1 -c "SELECT count(*) AS trips FROM trips;"

printf '\n\033[1;32mnyc_taxi initialized on production.\033[0m\n'
