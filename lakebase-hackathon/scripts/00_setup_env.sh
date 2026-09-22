#!/usr/bin/env bash
#
# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# 00_setup_env.sh — Verify the local environment for the Lakebase labs.
#   * Databricks CLI >= 0.285.0 (required for the `databricks postgres` API)
#   * An authenticated workspace profile
#   * psql client + jq present
#
# Uses only the Autoscaling `databricks postgres` API surface.
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
die() { printf '  \033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

MIN_CLI="0.285.0"

log "Checking Databricks CLI (>= ${MIN_CLI})"
command -v databricks >/dev/null 2>&1 || die "databricks CLI not found on PATH"
CLI_VER="$(databricks --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
[[ -n "$CLI_VER" ]] || die "could not parse 'databricks --version'"
if [[ "$(printf '%s\n%s\n' "$MIN_CLI" "$CLI_VER" | sort -V | head -1)" != "$MIN_CLI" ]]; then
  die "CLI ${CLI_VER} is older than the required ${MIN_CLI}"
fi
ok "databricks CLI ${CLI_VER}"

log "Validating workspace authentication (profile: ${PROFILE})"
databricks auth describe -p "$PROFILE" >/dev/null 2>&1 \
  || die "not authenticated for profile '${PROFILE}' (run: databricks auth login -p ${PROFILE})"
ok "authenticated (profile ${PROFILE})"

log "Checking psql client"
command -v psql >/dev/null 2>&1 || die "psql not found (install: brew install postgresql@16)"
ok "psql present — $(psql --version)"

log "Checking jq"
command -v jq >/dev/null 2>&1 || die "jq not found (install: brew install jq)"
ok "jq present — $(jq --version)"

printf '\n\033[1;32mEnvironment OK.\033[0m\n'
