import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

NOTEBOOKS_DIR = Path(__file__).parent / "notebooks"
sys.path.insert(0, str(NOTEBOOKS_DIR))

from pat_access import pat_auth_enabled, users_group_has_can_use


class PatAccessTest(unittest.TestCase):
    def test_pat_auth_enabled_requires_true_value(self) -> None:
        self.assertTrue(pat_auth_enabled({"enableTokensConfig": "true"}))
        self.assertTrue(pat_auth_enabled({"enableTokensConfig": "TRUE"}))
        self.assertFalse(pat_auth_enabled({"enableTokensConfig": "false"}))
        self.assertFalse(pat_auth_enabled({}))

    def test_users_group_requires_can_use(self) -> None:
        access_control_list = [
            {
                "group_name": "admins",
                "all_permissions": [{"permission_level": "CAN_MANAGE"}],
            },
            {
                "group_name": "users",
                "all_permissions": [{"permission_level": "CAN_USE"}],
            },
        ]

        self.assertTrue(users_group_has_can_use(access_control_list))

    def test_supports_sdk_permission_objects(self) -> None:
        access_control_list = [
            SimpleNamespace(
                group_name="users",
                all_permissions=[
                    SimpleNamespace(permission_level=SimpleNamespace(value="CAN_USE"))
                ],
            )
        ]

        self.assertTrue(users_group_has_can_use(access_control_list))

    def test_rejects_missing_users_can_use(self) -> None:
        access_control_list = [
            {
                "group_name": "users",
                "all_permissions": [{"permission_level": "CAN_MANAGE"}],
            }
        ]

        self.assertFalse(users_group_has_can_use(access_control_list))
        self.assertFalse(users_group_has_can_use(None))


if __name__ == "__main__":
    unittest.main()
