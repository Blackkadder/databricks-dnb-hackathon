# Databricks notebook source
"""Delete non-admin account users and their workspace folders, dry-running by default."""

# COMMAND ----------

from databricks.sdk import AccountClient, WorkspaceClient
from databricks.sdk.errors import BadRequest
from databricks.sdk.service.workspace import ObjectType

# COMMAND ----------

dbutils.widgets.text("account_host", "https://accounts.cloud.databricks.com")
dbutils.widgets.text("secret_scope", "hackathon-admin")
dbutils.widgets.text("account_id_secret_key", "account-id")
dbutils.widgets.text("admin_sp_username_secret_key", "admin-sp-username")
dbutils.widgets.text("admin_sp_client_secret_key", "admin-sp-client-secret")
dbutils.widgets.dropdown("run_live", "false", ["false", "true"])

account_host = dbutils.widgets.get("account_host").strip()
secret_scope = dbutils.widgets.get("secret_scope").strip()
account_id_secret_key = dbutils.widgets.get("account_id_secret_key").strip()
admin_sp_username_secret_key = dbutils.widgets.get(
    "admin_sp_username_secret_key"
).strip()
admin_sp_client_secret_key = dbutils.widgets.get(
    "admin_sp_client_secret_key"
).strip()
run_live = dbutils.widgets.get("run_live").strip().lower() == "true"

if not all(
    [
        secret_scope,
        account_id_secret_key,
        admin_sp_username_secret_key,
        admin_sp_client_secret_key,
    ]
):
    raise ValueError("All secret scope and key parameters are required")

account_id = dbutils.secrets.get(scope=secret_scope, key=account_id_secret_key).strip()
client_id = dbutils.secrets.get(
    scope=secret_scope, key=admin_sp_username_secret_key
).strip()
client_secret = dbutils.secrets.get(
    scope=secret_scope, key=admin_sp_client_secret_key
).strip()
if not all([account_id, client_id, client_secret]):
    raise ValueError("One or more account authentication secrets are empty")

# COMMAND ----------


def is_account_admin(user) -> bool:
    return any(
        getattr(role, "value", None) == "account_admin"
        for role in (user.roles or [])
    )


client = AccountClient(
    host=account_host,
    account_id=account_id,
    client_id=client_id,
    client_secret=client_secret,
)
workspace_client = WorkspaceClient(
    client_id=client_id,
    client_secret=client_secret,
)
users = list(client.users.list())
candidates = [user for user in users if not is_account_admin(user)]
admin_folder_paths = {
    f"/users/{user.user_name}".casefold()
    for user in users
    if is_account_admin(user) and user.user_name
}
workspace_folders = [
    item.path
    for item in workspace_client.workspace.list("/Users")
    if item.object_type == ObjectType.DIRECTORY
    and item.path
    and item.path.casefold() not in admin_folder_paths
]

mode = "LIVE DELETE" if run_live else "DRY RUN"
print(f"Mode: {mode}")
print(f"Non-admin users found: {len(candidates)}")
print(f"Non-admin or orphaned workspace folders found: {len(workspace_folders)}")

for workspace_folder in workspace_folders:
    print(
        f"Workspace folder: {workspace_folder} "
        f"({'delete' if run_live else 'would delete'})"
    )
    if run_live:
        try:
            workspace_client.workspace.delete(workspace_folder, recursive=True)
        except BadRequest as error:
            if "is protected" not in str(error):
                raise
            print(f"Workspace folder: {workspace_folder} (skipped: protected)")

for user in candidates:
    if not user.user_name:
        raise ValueError(f"Cannot process user without a user name: {user.id!r}")

    print(f"User: {user.user_name}")
    if run_live:
        if not user.id:
            raise ValueError(f"Cannot delete user without an ID: {user.user_name!r}")
        client.users.delete(user.id)

if run_live:
    print(f"Deleted {len(candidates)} non-admin users and their workspace folders.")
else:
    print("Dry run complete. No users or workspace folders were deleted.")
