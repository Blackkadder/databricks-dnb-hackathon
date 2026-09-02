# Databricks notebook source
"""Delete unprotected account groups, with dry-run behavior by default."""

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

PROTECTED_GROUPS = frozenset(
    {"account users", "workshop_admins", "workshop_users"}
)


def normalized_group_name(group) -> str | None:
    if not group.display_name:
        return None
    return group.display_name.strip().casefold()


client = AccountClient(
    host=account_host,
    account_id=account_id,
    client_id=client_id,
    client_secret=client_secret,
)
groups = list(client.groups.list())
present_names = {
    name for group in groups if (name := normalized_group_name(group)) is not None
}
missing_protected_groups = PROTECTED_GROUPS - present_names

if missing_protected_groups:
    missing = ", ".join(sorted(missing_protected_groups))
    raise RuntimeError(
        f"Safety check failed; protected groups are missing: {missing}. No groups deleted."
    )

candidates = [
    group
    for group in groups
    if (name := normalized_group_name(group)) is not None
    and name not in PROTECTED_GROUPS
]

mode = "LIVE DELETE" if run_live else "DRY RUN"
print(f"Mode: {mode}")
print(f"Protected groups: {', '.join(sorted(PROTECTED_GROUPS))}")
print(f"Groups selected for deletion: {len(candidates)}")

for group in candidates:
    print(group.display_name)
    if run_live:
        if not group.id:
            raise ValueError(f"Cannot delete group without an ID: {group.display_name!r}")
        client.groups.delete(group.id)

if run_live:
    print(f"Deleted {len(candidates)} unprotected account groups.")
else:
    print("Dry run complete. No groups were deleted.")
