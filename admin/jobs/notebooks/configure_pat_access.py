# Databricks notebook source
# ruff: noqa: F821
"""Allow all workspace users to create and use personal access tokens."""

# COMMAND ----------

import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import ResourceDoesNotExist
from databricks.sdk.service import iam
from pat_access import (
    PAT_AUTH_SETTING,
    PAT_REQUIRED_PERMISSION,
    PAT_USERS_GROUP,
    pat_auth_enabled,
    users_group_has_can_use,
)
from provisioning_csv import load_provisioning_rows, rows_for_workspace

# On a freshly created workspace the authorization/tokens ACL resource is not
# initialized until shortly after token auth is enabled, so both reads and the
# first write can return ResourceDoesNotExist. Retry the grant briefly.
TOKEN_ACL_ATTEMPTS = 6
TOKEN_ACL_INTERVAL_SECONDS = 10

# COMMAND ----------

dbutils.widgets.dropdown("run_live", "false", ["false", "true"])
dbutils.widgets.text(
    "csv_path", "/Volumes/admin/workshop_provisioning/user_provisioning/users.csv"
)
run_live = dbutils.widgets.get("run_live").strip().lower() == "true"
csv_path = dbutils.widgets.get("csv_path").strip()
if not csv_path:
    raise ValueError("csv_path is required")

workspace_client = WorkspaceClient()
workspace_id = workspace_client.get_workspace_id()
rows = rows_for_workspace(load_provisioning_rows(csv_path), workspace_id)
print(f"Current workspace ID: {workspace_id}")
print(f"Users selected for this workspace: {len(rows)}")
if not rows:
    dbutils.notebook.exit(
        f"No users are assigned to workspace {workspace_id}; no changes were made"
    )

mode = "LIVE" if run_live else "DRY RUN"
print(f"Mode: {mode}")

workspace_conf = workspace_client.workspace_conf.get_status(PAT_AUTH_SETTING)
try:
    token_permissions = workspace_client.permissions.get("authorization", "tokens")
    token_access_control_list = token_permissions.access_control_list
except ResourceDoesNotExist:
    # Fresh workspaces do not expose the token ACL resource until token
    # authentication is enabled. Treat that as an empty ACL so dry runs can
    # report the required change and live runs can initialize it below.
    token_access_control_list = []
auth_enabled = pat_auth_enabled(workspace_conf)
users_can_use = users_group_has_can_use(token_access_control_list)

print(
    "Personal access token authentication: " + ("enabled" if auth_enabled else "enable")
)
print(
    f"Token permission for {PAT_USERS_GROUP!r}: "
    + ("exists" if users_can_use else f"grant {PAT_REQUIRED_PERMISSION}")
)

if run_live:
    if not auth_enabled:
        workspace_client.workspace_conf.set_status(contents={PAT_AUTH_SETTING: "true"})
        print("Personal access token authentication: enabled")

    # Grant the built-in users group CAN_USE on tokens. On a brand-new workspace
    # the token ACL resource can lag behind enabling token auth, so retry on
    # ResourceDoesNotExist. Enabling token auth (verified below) is the hard
    # requirement; the explicit ACL is hardening, so a persistently
    # uninitialized ACL is a warning rather than a fatal error that would block
    # downstream schema creation.
    if not users_can_use:
        for attempt in range(1, TOKEN_ACL_ATTEMPTS + 1):
            try:
                workspace_client.permissions.update(
                    "authorization",
                    "tokens",
                    access_control_list=[
                        iam.AccessControlRequest(
                            group_name=PAT_USERS_GROUP,
                            permission_level=iam.PermissionLevel.CAN_USE,
                        )
                    ],
                )
                users_can_use = True
                print(
                    f"Token permission for {PAT_USERS_GROUP!r}: "
                    f"granted {PAT_REQUIRED_PERMISSION}"
                )
                break
            except ResourceDoesNotExist:
                if attempt == TOKEN_ACL_ATTEMPTS:
                    print(
                        "WARNING: token ACL resource is not yet initialized; "
                        f"'{PAT_USERS_GROUP}' {PAT_REQUIRED_PERMISSION} was not "
                        f"set. Token auth is enabled ({PAT_AUTH_SETTING}=true), "
                        "so users can create tokens; set the ACL once the "
                        "resource initializes."
                    )
                    break
                print(
                    "  waiting for token ACL resource "
                    f"({attempt}/{TOKEN_ACL_ATTEMPTS})"
                )
                time.sleep(TOKEN_ACL_INTERVAL_SECONDS)

    final_workspace_conf = workspace_client.workspace_conf.get_status(PAT_AUTH_SETTING)
    if not pat_auth_enabled(final_workspace_conf):
        raise RuntimeError("Personal access token authentication is not enabled")
    try:
        final_token_permissions = workspace_client.permissions.get(
            "authorization", "tokens"
        )
        if users_group_has_can_use(final_token_permissions.access_control_list):
            print("Personal access token readiness: verified")
        else:
            print(
                f"WARNING: group {PAT_USERS_GROUP!r} does not yet have "
                f"{PAT_REQUIRED_PERMISSION}; token auth is enabled so users can "
                "create tokens."
            )
    except ResourceDoesNotExist:
        print(
            "Personal access token authentication enabled; token ACL not yet "
            f"initialized so {PAT_USERS_GROUP!r} {PAT_REQUIRED_PERMISSION} is "
            "deferred until the resource is available."
        )
else:
    print("Dry run complete. No changes were made.")
