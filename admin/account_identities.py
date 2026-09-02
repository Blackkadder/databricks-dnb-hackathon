"""Helpers for managing Databricks account users and service principals."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from databricks.sdk import AccountClient

ACCOUNT_ADMIN_ROLE = "account_admin"


def _is_account_admin(identity: Any) -> bool:
    """Return whether an account identity has the account-admin SCIM role."""
    return any(
        getattr(role, "value", None) == ACCOUNT_ADMIN_ROLE
        for role in (getattr(identity, "roles", None) or [])
    )


def list_account_users(client: AccountClient | None = None) -> list[dict[str, Any]]:
    """List account users, including whether each user is an account admin."""
    client = client or AccountClient()
    return [
        {
            "id": user.id,
            "user_name": user.user_name,
            "display_name": user.display_name,
            "active": user.active,
            "is_account_admin": _is_account_admin(user),
        }
        for user in client.users.list()
    ]


def list_account_service_principals(
    client: AccountClient | None = None,
) -> list[dict[str, Any]]:
    """List account service principals, including account-admin status."""
    client = client or AccountClient()
    return [
        {
            "id": principal.id,
            "application_id": principal.application_id,
            "display_name": principal.display_name,
            "active": principal.active,
            "is_account_admin": _is_account_admin(principal),
        }
        for principal in client.service_principals.list()
    ]


def delete_non_admin_users(
    client: AccountClient | None = None,
    *,
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    """Delete non-admin account users, or only report them during a dry run."""
    client = client or AccountClient()
    results = []

    for user in client.users.list():
        if _is_account_admin(user):
            continue
        if not dry_run:
            if not user.id:
                raise ValueError(f"Cannot delete user without an ID: {user.user_name!r}")
            client.users.delete(user.id)
        results.append(
            {"id": user.id, "user_name": user.user_name, "deleted": not dry_run}
        )

    return results


def delete_non_admin_service_principals(
    client: AccountClient | None = None,
    *,
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    """Delete non-admin service principals, or report them during a dry run."""
    client = client or AccountClient()
    results = []

    for principal in client.service_principals.list():
        if _is_account_admin(principal):
            continue
        if not dry_run:
            if not principal.id:
                raise ValueError(
                    "Cannot delete service principal without an ID: "
                    f"{principal.application_id!r}"
                )
            client.service_principals.delete(principal.id)
        results.append(
            {
                "id": principal.id,
                "application_id": principal.application_id,
                "display_name": principal.display_name,
                "deleted": not dry_run,
            }
        )

    return results


def _read_users(
    source: str | Path | Iterable[str | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(source, (str, Path)):
        with Path(source).open(newline="", encoding="utf-8-sig") as csv_file:
            return [dict(row) for row in csv.DictReader(csv_file)]

    return [
        {"user_name": item} if isinstance(item, str) else dict(item)
        for item in source
    ]


def _parse_optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def add_account_users(
    source: str | Path | Iterable[str | Mapping[str, Any]],
    client: AccountClient | None = None,
) -> list[Any]:
    """Add users from a CSV path or a list of names/mappings.

    CSV rows and mappings support ``user_name`` (or ``email``), ``display_name``,
    ``external_id``, and ``active``. Existing user names are skipped.
    """
    client = client or AccountClient()
    existing = {
        user.user_name.casefold()
        for user in client.users.list()
        if user.user_name is not None
    }
    created = []

    for row in _read_users(source):
        user_name = str(row.get("user_name") or row.get("email") or "").strip()
        if not user_name:
            raise ValueError("Each user needs a non-empty 'user_name' or 'email'")
        if user_name.casefold() in existing:
            continue

        created.append(
            client.users.create(
                user_name=user_name,
                display_name=row.get("display_name") or None,
                external_id=row.get("external_id") or None,
                active=_parse_optional_bool(row.get("active")),
            )
        )
        existing.add(user_name.casefold())

    return created
