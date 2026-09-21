# Databricks notebook source
# ruff: noqa: F821
"""Provision account users, company groups, and per-user Git folders from CSV."""

# COMMAND ----------

import time

from databricks.sdk import AccountClient, WorkspaceClient
from databricks.sdk.errors import ResourceDoesNotExist
from databricks.sdk.service import iam, workspace
from provisioning_csv import load_provisioning_rows, rows_for_workspace

# COMMAND ----------

dbutils.widgets.text("account_host", "https://accounts.cloud.databricks.com")
dbutils.widgets.text("secret_scope", "hackathon-admin")
dbutils.widgets.text("account_id_secret_key", "account-id")
dbutils.widgets.text("admin_sp_username_secret_key", "admin-sp-username")
dbutils.widgets.text("admin_sp_client_secret_key", "admin-sp-client-secret")
dbutils.widgets.text(
    "csv_path", "/Volumes/admin/workshop_provisioning/user_provisioning/users.csv"
)
dbutils.widgets.dropdown("run_live", "false", ["false", "true"])
dbutils.widgets.dropdown(
    "grant_databricks_sql_access", "true", ["false", "true"]
)
dbutils.widgets.dropdown("provision_git_folders", "true", ["false", "true"])

account_host = dbutils.widgets.get("account_host").strip()
secret_scope = dbutils.widgets.get("secret_scope").strip()
account_id_secret_key = dbutils.widgets.get("account_id_secret_key").strip()
admin_sp_username_secret_key = dbutils.widgets.get(
    "admin_sp_username_secret_key"
).strip()
admin_sp_client_secret_key = dbutils.widgets.get("admin_sp_client_secret_key").strip()
csv_path = dbutils.widgets.get("csv_path").strip()
run_live = dbutils.widgets.get("run_live").strip().lower() == "true"
grant_databricks_sql_access = (
    dbutils.widgets.get("grant_databricks_sql_access").strip().lower() == "true"
)
provision_git_folders = (
    dbutils.widgets.get("provision_git_folders").strip().lower() == "true"
)

if not all(
    [
        account_host,
        secret_scope,
        account_id_secret_key,
        admin_sp_username_secret_key,
        admin_sp_client_secret_key,
        csv_path,
    ]
):
    raise ValueError("All job parameters are required")

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

REPO_URL = "https://github.com/Blackkadder/databricks-dnb-hackathon.git"
REPO_NAME = "databricks-dnb-hackathon"
REPO_BRANCH = "develop"
WORKSPACE_SYNC_ATTEMPTS = 30
WORKSPACE_SYNC_INTERVAL_SECONDS = 10
WORKSPACE_ACCESS_ENTITLEMENT = "workspace-access"
DATABRICKS_SQL_ACCESS_ENTITLEMENT = "databricks-sql-access"
WORKSPACE_ACCESS_PERMISSIONS = {
    iam.WorkspacePermission.USER,
    iam.WorkspacePermission.ADMIN,
}


def grant_repo_permission(repo_id: int, email: str) -> None:
    for attempt in range(1, WORKSPACE_SYNC_ATTEMPTS + 1):
        try:
            workspace_client.workspace.update_permissions(
                "repos",
                str(repo_id),
                access_control_list=[
                    workspace.WorkspaceObjectAccessControlRequest(
                        user_name=email,
                        permission_level=(
                            workspace.WorkspaceObjectPermissionLevel.CAN_MANAGE
                        ),
                    )
                ],
            )
            return
        except ResourceDoesNotExist:
            if attempt == WORKSPACE_SYNC_ATTEMPTS:
                raise
            print(
                "  waiting for account identity to sync to workspace "
                f"({attempt}/{WORKSPACE_SYNC_ATTEMPTS})"
            )
            time.sleep(WORKSPACE_SYNC_INTERVAL_SECONDS)


def wait_for_workspace_user(user_id: str, email: str) -> None:
    for attempt in range(1, WORKSPACE_SYNC_ATTEMPTS + 1):
        try:
            workspace_client.users.get(user_id)
            return
        except ResourceDoesNotExist:
            if attempt == WORKSPACE_SYNC_ATTEMPTS:
                raise
            print(
                f"  waiting for {email} workspace home "
                f"({attempt}/{WORKSPACE_SYNC_ATTEMPTS})"
            )
            time.sleep(WORKSPACE_SYNC_INTERVAL_SECONDS)


def ensure_workspace_group_entitlements(
    group_id: str, group_name: str, desired_entitlements: list[str]
) -> None:
    for attempt in range(1, WORKSPACE_SYNC_ATTEMPTS + 1):
        try:
            workspace_group = workspace_client.groups.get(group_id)
            break
        except ResourceDoesNotExist:
            if attempt == WORKSPACE_SYNC_ATTEMPTS:
                raise
            print(
                f"  waiting for {group_name!r} workspace group "
                f"({attempt}/{WORKSPACE_SYNC_ATTEMPTS})"
            )
            time.sleep(WORKSPACE_SYNC_INTERVAL_SECONDS)

    current_entitlements = {
        entitlement.value
        for entitlement in (workspace_group.entitlements or [])
        if entitlement.value
    }
    missing_entitlements = [
        entitlement
        for entitlement in desired_entitlements
        if entitlement not in current_entitlements
    ]
    if not missing_entitlements:
        print(
            "  group entitlements: exist " + ", ".join(desired_entitlements)
        )
        return

    workspace_client.groups.patch(
        group_id,
        operations=[
            iam.Patch(
                op=iam.PatchOp.ADD,
                path="entitlements",
                value=[{"value": value} for value in missing_entitlements],
            )
        ],
        schemas=[
            iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP
        ],
    )
    print("  group entitlements: granted " + ", ".join(missing_entitlements))


all_rows = load_provisioning_rows(csv_path)
workspace_client = WorkspaceClient()
workspace_id = workspace_client.get_workspace_id()
rows = rows_for_workspace(all_rows, workspace_id)

print(f"Current workspace ID: {workspace_id}")
print(f"Validated CSV users: {len(all_rows)}")
print(f"Users selected for this workspace: {len(rows)}")
print(f"Users skipped for other workspaces: {len(all_rows) - len(rows)}")
if not rows:
    dbutils.notebook.exit(
        f"No users are assigned to workspace {workspace_id}; no changes were made"
    )

account_client = AccountClient(
    host=account_host,
    account_id=account_id,
    client_id=client_id,
    client_secret=client_secret,
)
users_by_name = {
    user.user_name.casefold(): user
    for user in account_client.users.list()
    if user.user_name
}
groups_by_name = {
    group.display_name.casefold(): group
    for group in account_client.groups.list()
    if group.display_name
}
workspace_assignments = {
    str(assignment.principal.principal_id): set(assignment.permissions or [])
    for assignment in account_client.workspace_assignment.list(workspace_id)
    if assignment.principal and assignment.principal.principal_id is not None
}

mode = "LIVE" if run_live else "DRY RUN"
desired_entitlements = [WORKSPACE_ACCESS_ENTITLEMENT]
if grant_databricks_sql_access:
    desired_entitlements.append(DATABRICKS_SQL_ACCESS_ENTITLEMENT)
print(f"Mode: {mode}")
print(f"Company group entitlements: {', '.join(desired_entitlements)}")

for row in rows:
    email = row["email_address"]
    company = row["company"]
    user = users_by_name.get(email.casefold())
    group = groups_by_name.get(company.casefold())

    print(f"\n{email} | company={company}")
    if user is None:
        print("  account user: create")
        if run_live:
            user = account_client.users.create(user_name=email, active=True)
            users_by_name[email.casefold()] = user
    else:
        print("  account user: exists")

    if group is None:
        print("  account group: create")
        if run_live:
            group = account_client.groups.create(display_name=company)
            groups_by_name[company.casefold()] = group
    else:
        print("  account group: exists")

    if run_live:
        if not user or not user.id or not group or not group.id:
            raise ValueError(f"Missing user or group ID while provisioning {email!r}")

        current_group = account_client.groups.get(group.id)
        member_ids = {member.value for member in (current_group.members or [])}
        if user.id not in member_ids:
            account_client.groups.patch(
                group.id,
                operations=[
                    iam.Patch(
                        op=iam.PatchOp.ADD,
                        path="members",
                        value=[{"value": user.id}],
                    )
                ],
                schemas=[
                    iam.PatchSchema.URN_IETF_PARAMS_SCIM_API_MESSAGES_2_0_PATCH_OP
                ],
            )
            print("  group membership: added")
        else:
            print("  group membership: exists")

        if not WORKSPACE_ACCESS_PERMISSIONS.intersection(
            workspace_assignments.get(group.id, set())
        ):
            account_client.workspace_assignment.update(
                workspace_id,
                int(group.id),
                permissions=[iam.WorkspacePermission.USER],
            )
            workspace_assignments[group.id] = {iam.WorkspacePermission.USER}
            print("  workspace access: granted to group")
        else:
            print("  workspace access: exists")

        if not WORKSPACE_ACCESS_PERMISSIONS.intersection(
            workspace_assignments.get(user.id, set())
        ):
            account_client.workspace_assignment.update(
                workspace_id,
                int(user.id),
                permissions=[iam.WorkspacePermission.USER],
            )
            workspace_assignments[user.id] = {iam.WorkspacePermission.USER}
            print("  user workspace: assigned")
        else:
            print("  user workspace: exists")
        ensure_workspace_group_entitlements(
            group.id, company, desired_entitlements
        )
        wait_for_workspace_user(user.id, email)
    else:
        print("  group membership: ensure")
        print("  workspace access: ensure for company group")
        print("  user workspace: ensure")
        print(
            "  group entitlements: ensure " + ", ".join(desired_entitlements)
        )

    if not provision_git_folders:
        print("  Git folder: skipped (provision_git_folders=false)")
        continue

    repo_path = f"/Users/{email}/{REPO_NAME}"
    existing_repo = next(
        (
            repo
            for repo in workspace_client.repos.list(path_prefix=repo_path)
            if repo.path == repo_path
        ),
        None,
    )
    repo_id = existing_repo.id if existing_repo is not None else None
    if existing_repo is None:
        print(f"  Git folder: create {repo_path} at branch {REPO_BRANCH}")
        if run_live:
            created_repo = workspace_client.repos.create(
                url=REPO_URL,
                provider="gitHub",
                path=repo_path,
            )
            if created_repo.id is None:
                raise ValueError(f"Repo creation returned no ID for {email!r}")
            repo_id = created_repo.id
            # The repository's default branch is REPO_BRANCH. Avoid updating a
            # Git folder immediately after creation: the clone can still be
            # initializing its index, which makes the PATCH trigger a failing
            # fetch with ".git/index: index file open failed". Existing folders
            # are still corrected below if their branch differs.
            if created_repo.branch and created_repo.branch != REPO_BRANCH:
                workspace_client.repos.update(repo_id, branch=REPO_BRANCH)
                print(f"  Git branch: updated to {REPO_BRANCH}")
    else:
        print(f"  Git folder: exists {repo_path}")
        if (
            run_live
            and existing_repo.id is not None
            and existing_repo.branch != REPO_BRANCH
        ):
            workspace_client.repos.update(existing_repo.id, branch=REPO_BRANCH)
            print(f"  Git branch: updated to {REPO_BRANCH}")

    if run_live:
        if repo_id is None:
            raise ValueError(f"Git folder has no ID for {email!r}")
        grant_repo_permission(repo_id, email)
        print("  Git folder permission: CAN_MANAGE")
    else:
        print("  Git folder permission: ensure CAN_MANAGE")

print(
    "\nProvisioning complete."
    if run_live
    else "\nDry run complete. No changes were made."
)
