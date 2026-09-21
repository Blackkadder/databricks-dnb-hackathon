"""Validation and workspace filtering for the shared provisioning CSV."""

import csv
import re
from pathlib import Path


EXPECTED_HEADERS = {"email_address", "company", "workspace_id"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_provisioning_rows(path: str) -> list[dict[str, str]]:
    """Load and validate all rows before any workspace-specific filtering."""
    with Path(path).open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        headers = set(reader.fieldnames or [])
        if headers != EXPECTED_HEADERS:
            raise ValueError(
                f"CSV headers must be exactly {sorted(EXPECTED_HEADERS)}; "
                f"got {sorted(headers)}"
            )

        rows: list[dict[str, str]] = []
        seen_emails: dict[str, tuple[str, str]] = {}
        workspace_by_company: dict[str, tuple[str, str]] = {}
        for line_number, raw_row in enumerate(reader, start=2):
            email = (raw_row.get("email_address") or "").strip().lower()
            company = (raw_row.get("company") or "").strip()
            raw_workspace_id = (raw_row.get("workspace_id") or "").strip()

            if not EMAIL_PATTERN.fullmatch(email):
                raise ValueError(
                    f"Invalid email_address on CSV line {line_number}: {email!r}"
                )
            if not company:
                raise ValueError(f"company is required on CSV line {line_number}")
            if not raw_workspace_id.isdigit() or int(raw_workspace_id) <= 0:
                raise ValueError(
                    f"workspace_id must be a positive integer on CSV line "
                    f"{line_number}: {raw_workspace_id!r}"
                )

            workspace_id = str(int(raw_workspace_id))
            company_key = company.casefold()
            previous_company_assignment = workspace_by_company.get(company_key)
            if (
                previous_company_assignment
                and previous_company_assignment[1] != workspace_id
            ):
                raise ValueError(
                    f"Company {company!r} is assigned to multiple workspaces: "
                    f"{previous_company_assignment[1]} and {workspace_id}"
                )
            workspace_by_company.setdefault(company_key, (company, workspace_id))

            assignment = (company_key, workspace_id)
            previous_assignment = seen_emails.get(email)
            if previous_assignment and previous_assignment != assignment:
                raise ValueError(
                    f"User {email!r} is assigned to multiple companies or workspaces"
                )
            if previous_assignment:
                continue

            seen_emails[email] = assignment
            rows.append(
                {
                    "email_address": email,
                    "company": company,
                    "workspace_id": workspace_id,
                }
            )

    if not rows:
        raise ValueError("CSV must contain at least one user")
    return rows


def rows_for_workspace(
    rows: list[dict[str, str]], workspace_id: int | str
) -> list[dict[str, str]]:
    """Return only rows assigned to the workspace running the job."""
    current_workspace_id = str(workspace_id).strip()
    return [row for row in rows if row["workspace_id"] == current_workspace_id]
