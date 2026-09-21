# Databricks notebook source
# ruff: noqa: F821
"""Allow all workspace users to create and use personal access tokens."""

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import iam
from pat_access import (
    PAT_AUTH_SETTING,
    PAT_REQUIRED_PERMISSION,
    PAT_USERS_GROUP,
    pat_auth_enabled,
    users_group_has_can_use,
)
from provisioning_csv import load_provisioning_rows, rows_for_workspace

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
token_permissions = workspace_client.permissions.get("authorization", "tokens")
auth_enabled = pat_auth_enabled(workspace_conf)
users_can_use = users_group_has_can_use(token_permissions.access_control_list)

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

    if not users_can_use:
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
        print(
            f"Token permission for {PAT_USERS_GROUP!r}: "
            f"granted {PAT_REQUIRED_PERMISSION}"
        )

    final_workspace_conf = workspace_client.workspace_conf.get_status(PAT_AUTH_SETTING)
    final_token_permissions = workspace_client.permissions.get(
        "authorization", "tokens"
    )
    if not pat_auth_enabled(final_workspace_conf):
        raise RuntimeError("Personal access token authentication is not enabled")
    if not users_group_has_can_use(final_token_permissions.access_control_list):
        raise RuntimeError(
            f"Group {PAT_USERS_GROUP!r} does not have {PAT_REQUIRED_PERMISSION}"
        )
    print("Personal access token readiness: verified")
else:
    print("Dry run complete. No changes were made.")
