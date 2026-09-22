#!/usr/bin/env bash
#
# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# 99_teardown.sh — Delete all Lakebase resources created by the labs.
# Purges every non-`production` branch, then the project itself (which cascades
# to the production branch, endpoints, databases, and data).
#
# HARD delete (purge=true): because the labs always reuse the same per-user project id,
# we purge rather than soft-delete so no retention-window tombstone is left behind — the
# name is immediately reusable on the next run. (The CLI has no --purge flag, so the
# purge calls go through the raw `databricks api delete ...?purge=true` endpoint.)
#
# Idempotent + safe to re-run.
#   Usage: 99_teardown.sh [-p|--profile PROFILE] [-y|--yes]
set -euo pipefail

PROFILE="DEFAULT"
ASSUME_YES="no"
usage() { echo "Usage: $0 [-p|--profile PROFILE] [-y|--yes]"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile) PROFILE="${2:?--profile needs a value}"; shift 2 ;;
    -y|--yes)     ASSUME_YES="yes"; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

log() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
ok()  { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }

# Per-user project id — must match the one the other scripts created. Uniqueness is
# guaranteed by the numeric Databricks user id, so a user can only ever tear down their
# OWN project, never a neighbour's.
_me="$(databricks current-user me -p "$PROFILE" -o json)"
_uid="$(jq -r '.id' <<<"$_me")"
_slug="$(jq -r '.userName' <<<"$_me" | sed -E 's/@.*$//' | tr '[:upper:]' '[:lower:]' \
         | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-20 | sed -E 's/-+$//')"
[[ -n "$_uid" ]] || { echo "could not resolve Databricks user id" >&2; exit 1; }
PROJECT_ID="lakebase-lab-${_slug:-user}-${_uid}"
PROJECT="projects/${PROJECT_ID}"

dbx() { databricks postgres "$@" -p "$PROFILE" -o json; }

# --- Nothing to do if the project is already gone ---
# NOTE: delete-project is a *soft* delete — `get-project` still resolves a deleted
# project by name during its retention window, so we check `list-projects` membership
# (which drops deleted projects) to decide whether there is anything to remove.
if ! dbx list-projects | jq -e --arg p "$PROJECT" '.[] | select(.name == $p)' >/dev/null 2>&1; then
  ok "project ${PROJECT} not present in list-projects — nothing to tear down"
  exit 0
fi

# --- Confirm (unless -y) ---
if [[ "$ASSUME_YES" != "yes" ]]; then
  printf '\033[1;31mThis will permanently delete project %s and ALL its data.\033[0m\n' "$PROJECT"
  read -r -p "Type 'yes' to continue: " reply
  [[ "$reply" == "yes" ]] || { echo "aborted."; exit 1; }
fi

# Hard-delete a resource by its full name via the raw API (purge=true). The CLI's
# delete-branch / delete-project have no --purge flag, so we call the REST endpoint.
purge() { databricks api delete "/api/2.0/postgres/$1?purge=true" -p "$PROFILE" >/dev/null; }

# --- 1. Purge every non-production branch (children before the project) ---
log "Purging non-production branches"
BRANCHES="$(dbx list-branches "$PROJECT" \
  | jq -r '.[] | select(.name | endswith("/branches/production") | not) | .name')"
if [[ -z "$BRANCHES" ]]; then
  ok "no extra branches"
else
  while IFS= read -r branch; do
    [[ -n "$branch" ]] || continue
    log "Purging branch ${branch##*/branches/}"
    purge "$branch"
    ok "purged ${branch##*/branches/}"
  done <<< "$BRANCHES"
fi

# --- 2. Purge the project (hard delete; cascades to everything remaining) ---
# purge=true leaves no soft-delete tombstone, so the project id is reusable immediately.
log "Purging project ${PROJECT_ID}"
purge "$PROJECT"
ok "project purged"

printf '\n\033[1;32mTeardown complete — project purged (name reusable now).\033[0m\n'
