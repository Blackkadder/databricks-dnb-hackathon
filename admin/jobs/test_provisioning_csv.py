import sys
import tempfile
import unittest
from pathlib import Path

NOTEBOOKS_DIR = Path(__file__).parent / "notebooks"
sys.path.insert(0, str(NOTEBOOKS_DIR))

from provisioning_csv import load_provisioning_rows, rows_for_workspace  # noqa: E402


class ProvisioningCsvTest(unittest.TestCase):
    def write_csv(self, directory: str, content: str) -> str:
        path = Path(directory) / "users.csv"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_loads_and_filters_shared_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_csv(
                directory,
                "email_address,company,workspace_id\n"
                "one@example.com,Team One,101\n"
                "two@example.com,Team Two,202\n",
            )
            rows = load_provisioning_rows(path)

        self.assertEqual(
            rows_for_workspace(rows, 101),
            [
                {
                    "email_address": "one@example.com",
                    "company": "Team One",
                    "workspace_id": "101",
                }
            ],
        )
        self.assertEqual(rows_for_workspace(rows, "303"), [])

    def test_rejects_company_assigned_to_multiple_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_csv(
                directory,
                "email_address,company,workspace_id\n"
                "one@example.com,Team One,101\n"
                "two@example.com,team one,202\n",
            )

            with self.assertRaisesRegex(ValueError, "assigned to multiple workspaces"):
                load_provisioning_rows(path)

    def test_rejects_invalid_workspace_ids(self) -> None:
        for workspace_id in ["", "abc", "0", "-1", "1.5"]:
            with self.subTest(workspace_id=workspace_id):
                with tempfile.TemporaryDirectory() as directory:
                    path = self.write_csv(
                        directory,
                        "email_address,company,workspace_id\n"
                        f"one@example.com,Team One,{workspace_id}\n",
                    )

                    with self.assertRaisesRegex(
                        ValueError, "workspace_id must be a positive integer"
                    ):
                        load_provisioning_rows(path)

    def test_requires_workspace_id_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_csv(
                directory,
                "email_address,company\n"
                "one@example.com,Team One\n",
            )

            with self.assertRaisesRegex(ValueError, "CSV headers must be exactly"):
                load_provisioning_rows(path)


if __name__ == "__main__":
    unittest.main()
