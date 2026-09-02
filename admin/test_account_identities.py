# Databricks notebook source
"""Safe tests for the account identity helpers.

Leave ``RUN_LIVE`` set to ``False`` to test against in-memory identities only.
Live mode performs listings and deletion dry-runs; it never adds or deletes
identities in the Databricks account.
"""

# COMMAND ----------

from dataclasses import dataclass, field
from typing import Any

from databricks.sdk import AccountClient

from account_identities import (
    add_account_users,
    delete_non_admin_service_principals,
    delete_non_admin_users,
    list_account_service_principals,
    list_account_users,
)

# COMMAND ----------

# Keep this False for safe, local-only testing.
RUN_LIVE = False

# COMMAND ----------


@dataclass
class Role:
    value: str


@dataclass
class Identity:
    id: str
    display_name: str
    active: bool = True
    user_name: str | None = None
    application_id: str | None = None
    roles: list[Role] = field(default_factory=list)


class FakeIdentityApi:
    def __init__(self, identities: list[Identity]) -> None:
        self.identities = identities
        self.deleted: list[str] = []

    def list(self):
        return iter(self.identities)

    def delete(self, identity_id: str) -> None:
        self.deleted.append(identity_id)

    def create(self, **values: Any) -> Identity:
        identity = Identity(
            id=f"new-{len(self.identities) + 1}",
            display_name=values.get("display_name") or values["user_name"],
            user_name=values["user_name"],
            active=values.get("active") is not False,
        )
        self.identities.append(identity)
        return identity


class FakeAccountClient:
    def __init__(self) -> None:
        self.users = FakeIdentityApi(
            [
                Identity(
                    id="user-admin",
                    user_name="admin@example.com",
                    display_name="Admin",
                    roles=[Role("account_admin")],
                ),
                Identity(
                    id="user-member",
                    user_name="member@example.com",
                    display_name="Member",
                ),
            ]
        )
        self.service_principals = FakeIdentityApi(
            [
                Identity(
                    id="sp-admin",
                    application_id="admin-app",
                    display_name="Admin service principal",
                    roles=[Role("account_admin")],
                ),
                Identity(
                    id="sp-member",
                    application_id="worker-app",
                    display_name="Worker service principal",
                ),
            ]
        )

# COMMAND ----------


def run_safe_tests() -> dict[str, Any]:
    """Exercise every helper without connecting to Databricks."""
    client = FakeAccountClient()
    results = {
        "users": list_account_users(client),
        "service_principals": list_account_service_principals(client),
        "user_deletion_dry_run": delete_non_admin_users(client),
        "service_principal_deletion_dry_run": (
            delete_non_admin_service_principals(client)
        ),
        "added_users": add_account_users(
            [
                "new-user@example.com",
                {"email": "another-user@example.com", "active": "false"},
                "member@example.com",
            ],
            client,
        ),
    }
    assert client.users.deleted == []
    assert client.service_principals.deleted == []
    assert len(client.users.identities) == 4
    return results


def run_live_dry_run() -> dict[str, Any]:
    """Run only non-mutating operations using notebook credentials."""
    client = AccountClient()
    return {
        "users": list_account_users(client),
        "service_principals": list_account_service_principals(client),
        "user_deletion_dry_run": delete_non_admin_users(client, dry_run=True),
        "service_principal_deletion_dry_run": (
            delete_non_admin_service_principals(client, dry_run=True)
        ),
    }

# COMMAND ----------

results = run_live_dry_run() if RUN_LIVE else run_safe_tests()
print(
    "PASS: live listings and dry-runs only."
    if RUN_LIVE
    else "PASS: all operations used in-memory test data only."
)
display(results)
