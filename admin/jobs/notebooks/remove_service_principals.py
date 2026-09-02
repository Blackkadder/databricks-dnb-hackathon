# Databricks notebook source
"""Delete non-admin account service principals, dry-running by default."""

# COMMAND ----------

from databricks.sdk import AccountClient

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


def is_account_admin(principal) -> bool:
    return any(
        getattr(role, "value", None) == "account_admin"
        for role in (principal.roles or [])
    )


client = AccountClient(
    host=account_host,
    account_id=account_id,
    client_id=client_id,
    client_secret=client_secret,
)
principals = list(client.service_principals.list())
candidates = [principal for principal in principals if not is_account_admin(principal)]

mode = "LIVE DELETE" if run_live else "DRY RUN"
print(f"Mode: {mode}")
print(f"Non-admin service principals found: {len(candidates)}")

for principal in candidates:
    identity = principal.display_name or principal.application_id or principal.id
    print(f"{identity} | application_id={principal.application_id}")
    if run_live:
        if not principal.id:
            raise ValueError(
                "Cannot delete service principal without an ID: "
                f"{principal.application_id!r}"
            )
        client.service_principals.delete(principal.id)

if run_live:
    print(f"Deleted {len(candidates)} non-admin service principals.")
else:
    print("Dry run complete. No service principals were deleted.")
