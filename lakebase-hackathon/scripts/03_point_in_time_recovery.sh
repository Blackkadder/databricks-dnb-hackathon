#!/usr/bin/env bash
#
# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# 03_point_in_time_recovery.sh — Simulate accidental data loss on production and
# recover it by branching from a point in time (PITR). In Lakebase the branch
# mechanism IS the restore: branch from `source_branch_time` before the incident.
#
# Uses only the `databricks postgres` API.
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
RECOVERY="recovery-branch"
RBRANCH="${PROJECT}/branches/${RECOVERY}"
DB="nyc_taxi"

dbx() { databricks postgres "$@" -p "$PROFILE" -o json; }

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

# --- 0. Connect to production; require a populated trips table ---
log "Connecting to production"
EP_PROD="$(dbx list-endpoints "$PROD_BRANCH" | jq -r '.[0].name')"
IFS='|' read -r PHOST PTOKEN <<< "$(conn_for_endpoint "$EP_PROD")"
export PGPASSWORD="$PTOKEN"
PG_P="host=${PHOST} port=5432 dbname=${DB} user=${EMAIL} sslmode=require"
CNT="$(psql "$PG_P" -tAc "SELECT count(*) FROM trips" 2>/dev/null || echo 0)"
[[ "${CNT:-0}" -gt 0 ]] || { echo "trips is empty/missing on production — run 01 first" >&2; exit 1; }
ok "production has ${CNT} trips"

# --- 1. Capture the pre-corruption recovery point T0 ---
log "Capturing recovery point T0"
T0="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
ok "T0=${T0}"
sleep 8   # ensure T0 strictly precedes the destructive change

# --- 2. Simulate the disaster (T1): drop the table on production ---
log "Simulating data loss (DROP TABLE trips) on production"
psql "$PG_P" -v ON_ERROR_STOP=1 -c "DROP TABLE IF EXISTS trips CASCADE;"
if [[ "$(psql "$PG_P" -tAc "SELECT to_regclass('cabs.trips') IS NULL")" == "t" ]]; then
  ok "trips dropped on production"
fi

# --- 3. Create the recovery branch from production @ T0 (idempotent) ---
log "Creating ${RECOVERY} from production @ T0 (point-in-time)"
if databricks postgres get-branch "$RBRANCH" -p "$PROFILE" >/dev/null 2>&1; then
  ok "recovery branch already exists"
else
  databricks postgres create-branch "$PROJECT" "$RECOVERY" -p "$PROFILE" \
    --json "{\"spec\": {\"source_branch\": \"${PROD_BRANCH}\", \"source_branch_time\": \"${T0}\", \"ttl\": \"86400s\"}}" >/dev/null
  ok "recovery branch created"
fi

# --- 4. Attach an endpoint to the recovery branch (idempotent) ---
REP="${RBRANCH}/endpoints/primary"
log "Creating endpoint on ${RECOVERY}"
if databricks postgres get-endpoint "$REP" -p "$PROFILE" >/dev/null 2>&1; then
  ok "endpoint already exists"
else
  databricks postgres create-endpoint "$RBRANCH" primary -p "$PROFILE" \
    --json '{"spec": {"endpoint_type": "ENDPOINT_TYPE_READ_WRITE", "autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 2.0}}' >/dev/null
  ok "endpoint created"
fi

# --- 5. Verify the data was recovered at T0 ---
log "Verifying recovered data on ${RECOVERY}"
IFS='|' read -r RHOST RTOKEN <<< "$(conn_for_endpoint "$REP")"
export PGPASSWORD="$RTOKEN"
PG_R="host=${RHOST} port=5432 dbname=${DB} user=${EMAIL} sslmode=require"
psql "$PG_R" -v ON_ERROR_STOP=1 -c "SELECT count(*) AS recovered_trips FROM trips;"
REC="$(psql "$PG_R" -tAc "SELECT count(*) FROM trips")"
[[ "${REC:-0}" -gt 0 ]] || { echo "recovery failed: no trips at T0" >&2; exit 1; }

printf '\n\033[1;32mPITR OK — recovered %s trips from T0 on %s.\033[0m\n' "$REC" "$RECOVERY"
