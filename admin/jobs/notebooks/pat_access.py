"""Shared helpers for evaluating workspace personal access token readiness."""

from typing import Any

PAT_AUTH_SETTING = "enableTokensConfig"
PAT_USERS_GROUP = "users"
PAT_REQUIRED_PERMISSION = "CAN_USE"


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def pat_auth_enabled(workspace_conf: dict[str, str]) -> bool:
    """Return whether workspace PAT authentication is explicitly enabled."""
    return str(workspace_conf.get(PAT_AUTH_SETTING, "")).strip().lower() == "true"


def users_group_has_can_use(access_control_list: list[Any] | None) -> bool:
    """Return whether the built-in users group has direct CAN_USE token access."""
    for entry in access_control_list or []:
        group_name = str(_field(entry, "group_name", "")).strip().casefold()
        if group_name != PAT_USERS_GROUP:
            continue
        for permission in _field(entry, "all_permissions", []) or []:
            permission_level = _field(permission, "permission_level")
            permission_value = _field(permission_level, "value", permission_level)
            if str(permission_value).strip().upper() == PAT_REQUIRED_PERMISSION:
                return True
    return False
