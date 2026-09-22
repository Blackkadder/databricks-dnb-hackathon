#!/usr/bin/env bash
#
# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# 02_branch_and_migrate.sh — Branch `nyc_taxi` from production, apply one isolated
# schema migration on the branch, and prove it is NOT visible on production.
#
# Migration: add the real NYC TLC `congestion_surcharge` column + backfill Manhattan.
# Idempotent. Uses only the `databricks postgres` API.
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
_me="$(databricks current-user me -p "$PROFILE" -o json)"
_uid="$(jq -r '.id' <<<"$_me")"
_slug="$(jq -r '.userName' <<<"$_me" | sed -E 's/@.*$//' | tr '[:upper:]' '[:lower:]' \
         | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-20 | sed -E 's/-+$//')"
[[ -n "$_uid" ]] || { echo "could not resolve Databricks user id" >&2; exit 1; }
PROJECT_ID="lakebase-lab-${_slug:-user}-${_uid}"
PROJECT="projects/${PROJECT_ID}"
PROD_BRANCH="${PROJECT}/branches/production"
FEATURE="feature-x"
FBRANCH="${PROJECT}/branches/${FEATURE}"
DB="nyc_taxi"

dbx() { databricks postgres "$@" -p "$PROFILE" -o json; }

# Wait for an endpoint to be usable, then echo "host|token".
conn_for_endpoint() {
  local ep="$1" st="" host token
  for _ in $(seq 1 60); do
    st="$(dbx get-endpoint "$ep" | jq -r '.status.current_state')"
    [[ "$st" == "ACTIVE" || "$st" == "IDLE" ]] && break
    sleep 5
  done
  host="$(dbx get-endpoint "$ep" | jq -r '.status.hosts.host')"
  token="$(dbx generate-database-credential "$ep" | jq -r '.token')"
  printf '%s|%s' "$host" "$token"
}

EMAIL="$(databricks current-user me -p "$PROFILE" -o json | jq -r '.userName')"

# --- 1. Create the feature branch (7-day TTL; idempotent) ---
log "Creating branch ${FEATURE} (7-day TTL)"
if databricks postgres get-branch "$FBRANCH" -p "$PROFILE" >/dev/null 2>&1; then
  ok "branch already exists"
else
  databricks postgres create-branch "$PROJECT" "$FEATURE" -p "$PROFILE" \
    --json "{\"spec\": {\"source_branch\": \"${PROD_BRANCH}\", \"ttl\": \"604800s\"}}" >/dev/null
  ok "branch created"
fi

# --- 2. Attach a read-write autoscaling endpoint (idempotent) ---
FEP="${FBRANCH}/endpoints/primary"
log "Creating read-write endpoint on ${FEATURE} (autoscale 0.5–2.0 CU)"
if databricks postgres get-endpoint "$FEP" -p "$PROFILE" >/dev/null 2>&1; then
  ok "endpoint already exists"
else
  databricks postgres create-endpoint "$FBRANCH" primary -p "$PROFILE" \
    --json '{"spec": {"endpoint_type": "ENDPOINT_TYPE_READ_WRITE", "autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 2.0}}' >/dev/null
  ok "endpoint created"
fi

# --- 3. Apply the isolated migration on feature-x ---
log "Applying isolated migration on ${FEATURE}"
IFS='|' read -r FHOST FTOKEN <<< "$(conn_for_endpoint "$FEP")"
export PGPASSWORD="$FTOKEN"
PG_F="host=${FHOST} port=5432 dbname=${DB} user=${EMAIL} sslmode=require"
psql "$PG_F" -v ON_ERROR_STOP=1 <<'SQL'
ALTER TABLE trips ADD COLUMN IF NOT EXISTS congestion_surcharge NUMERIC(8,2) DEFAULT 0;
UPDATE trips t
SET congestion_surcharge = 2.50
FROM taxi_zones z
WHERE z.location_id = t.pickup_location_id
  AND z.borough = 'Manhattan';
SQL
ok "migration applied on ${FEATURE}"
psql "$PG_F" -v ON_ERROR_STOP=1 \
  -c "SELECT trip_id, total_amount, congestion_surcharge FROM trips ORDER BY trip_id;"

# --- 4. Prove isolation: the column must be ABSENT on production ---
log "Verifying isolation (column must be absent on production)"
EP_PROD="$(dbx list-endpoints "$PROD_BRANCH" | jq -r '.[0].name')"
IFS='|' read -r PHOST PTOKEN <<< "$(conn_for_endpoint "$EP_PROD")"
export PGPASSWORD="$PTOKEN"
PG_P="host=${PHOST} port=5432 dbname=${DB} user=${EMAIL} sslmode=require"
if psql "$PG_P" -tAc "SELECT congestion_surcharge FROM trips LIMIT 1" >/dev/null 2>&1; then
  echo "  ✗ column unexpectedly present on production (NOT isolated)" >&2
  exit 1
else
  ok "confirmed: congestion_surcharge is absent on production"
fi

cat <<'EOF'

To PROMOTE (there is no git-style branch merge — promote the migration, not the branch):
  re-apply the SAME migration to production once validated, e.g. via CI on merge:
    ALTER TABLE trips ADD COLUMN congestion_surcharge NUMERIC(8,2) DEFAULT 0;
    UPDATE trips t SET congestion_surcharge = 2.50
      FROM taxi_zones z
      WHERE z.location_id = t.pickup_location_id AND z.borough = 'Manhattan';
EOF
printf '\n\033[1;32mBranch + isolated migration validated on %s.\033[0m\n' "$FEATURE"
