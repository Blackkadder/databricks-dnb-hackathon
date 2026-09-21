#!/usr/bin/env python3
"""Assign hackathon teams to Databricks workspaces and validate the result."""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

OUTPUT_HEADERS = ["email_address", "company", "workspace_id"]
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_CANDIDATES = ("email_address", "email", "email address", "e-mail")
TEAM_CANDIDATES = ("team", "company", "organization", "organisation")


class RosterError(ValueError):
    """Raised when a roster or assignment is invalid."""


@dataclass
class Team:
    name: str
    members: list[str] = field(default_factory=list)


@dataclass
class Workspace:
    workspace_id: str
    teams: list[Team] = field(default_factory=list)

    @property
    def member_count(self) -> int:
        return sum(len(team.members) for team in self.teams)


def parse_workspace_id(value: str) -> str:
    """Return a normalized positive workspace ID from an ID or Databricks URL."""
    raw_value = value.strip()
    candidate = raw_value
    if "://" in raw_value:
        query_values = parse_qs(urlparse(raw_value).query).get("o", [])
        if len(query_values) != 1:
            raise RosterError(
                f"Workspace URL must contain exactly one numeric 'o' parameter: {value!r}"
            )
        candidate = query_values[0].strip()

    if not candidate.isdigit() or int(candidate) <= 0:
        raise RosterError(f"Workspace ID must be a positive integer: {value!r}")
    return str(int(candidate))


def resolve_column(
    headers: list[str], explicit: str | None, candidates: tuple[str, ...], label: str
) -> str:
    """Resolve a source column case-insensitively."""
    normalized = {header.strip().casefold(): header for header in headers}
    if explicit:
        match = normalized.get(explicit.strip().casefold())
        if not match:
            raise RosterError(
                f"{label} column {explicit!r} was not found; headers are {headers}"
            )
        return match

    for candidate in candidates:
        match = normalized.get(candidate.casefold())
        if match:
            return match
    raise RosterError(
        f"Could not detect the {label} column; use --{label}-column. Headers are {headers}"
    )


def load_roster(
    path: Path, email_column: str | None, team_column: str | None
) -> tuple[list[dict[str, str]], dict[str, Team], str, str, int]:
    """Load source rows, normalize users, and group them by case-insensitive team."""
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        headers = reader.fieldnames or []
        if not headers:
            raise RosterError("Roster CSV has no header row")
        resolved_email = resolve_column(
            headers, email_column, EMAIL_CANDIDATES, "email"
        )
        resolved_team = resolve_column(headers, team_column, TEAM_CANDIDATES, "team")

        unique_rows: list[dict[str, str]] = []
        teams: dict[str, Team] = {}
        seen_emails: dict[str, str] = {}
        duplicates = 0

        for line_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise RosterError(
                    f"Roster line {line_number} has more fields than the header row"
                )
            if not any((value or "").strip() for value in raw_row.values()):
                continue
            email = (raw_row.get(resolved_email) or "").strip().lower()
            team_name = (raw_row.get(resolved_team) or "").strip()
            if not EMAIL_PATTERN.fullmatch(email):
                raise RosterError(
                    f"Invalid email in {resolved_email!r} on line {line_number}: {email!r}"
                )
            if not team_name:
                raise RosterError(
                    f"Team is required in {resolved_team!r} on line {line_number}"
                )

            team_key = team_name.casefold()
            previous_team = seen_emails.get(email)
            if previous_team and previous_team != team_key:
                raise RosterError(
                    f"User {email!r} belongs to multiple teams: "
                    f"{teams[previous_team].name!r} and {team_name!r}"
                )
            if previous_team:
                duplicates += 1
                continue

            seen_emails[email] = team_key
            team = teams.setdefault(team_key, Team(name=team_name))
            team.members.append(email)
            unique_rows.append({"email": email, "team_key": team_key})

    if not unique_rows:
        raise RosterError("Roster must contain at least one participant")
    return unique_rows, teams, resolved_email, resolved_team, duplicates


def parse_pinned_assignments(
    raw_assignments: list[str], teams: dict[str, Team], workspace_ids: list[str]
) -> dict[str, str]:
    """Parse TEAM=WORKSPACE pins and return team-key to workspace-ID mappings."""
    pinned: dict[str, str] = {}
    for raw_assignment in raw_assignments:
        team_name, separator, raw_workspace = raw_assignment.partition("=")
        if not separator or not team_name.strip() or not raw_workspace.strip():
            raise RosterError(
                f"Assignment must use the form 'Team=workspace': {raw_assignment!r}"
            )
        team_key = team_name.strip().casefold()
        if team_key not in teams:
            raise RosterError(f"Pinned team was not found in the roster: {team_name!r}")
        workspace_id = parse_workspace_id(raw_workspace)
        if workspace_id not in workspace_ids:
            raise RosterError(
                f"Pinned workspace {workspace_id} was not supplied with --workspace"
            )
        previous = pinned.get(team_key)
        if previous and previous != workspace_id:
            raise RosterError(
                f"Team {teams[team_key].name!r} has conflicting pinned workspaces"
            )
        pinned[team_key] = workspace_id
    return pinned


def assign_teams(
    teams: dict[str, Team], workspace_ids: list[str], pinned: dict[str, str]
) -> tuple[dict[str, str], list[Workspace]]:
    """Assign whole teams using deterministic largest-first load balancing."""
    workspaces = [Workspace(workspace_id=value) for value in workspace_ids]
    by_id = {workspace.workspace_id: workspace for workspace in workspaces}
    assignments: dict[str, str] = {}

    for team_key in sorted(pinned, key=lambda key: teams[key].name.casefold()):
        workspace_id = pinned[team_key]
        by_id[workspace_id].teams.append(teams[team_key])
        assignments[team_key] = workspace_id

    unassigned = [
        (team_key, team)
        for team_key, team in teams.items()
        if team_key not in assignments
    ]
    unassigned.sort(key=lambda item: (-len(item[1].members), item[1].name.casefold()))

    for team_key, team in unassigned:
        _, workspace = min(
            enumerate(workspaces),
            key=lambda item: (
                item[1].member_count,
                len(item[1].teams),
                item[0],
            ),
        )
        workspace.teams.append(team)
        assignments[team_key] = workspace.workspace_id

    return assignments, workspaces


def write_output(
    output_path: Path,
    source_path: Path,
    rows: list[dict[str, str]],
    teams: dict[str, Team],
    assignments: dict[str, str],
) -> None:
    """Atomically write a provisioning CSV while refusing to replace the source."""
    if output_path.resolve() == source_path.resolve():
        raise RosterError("Output path must differ from the source roster path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_name = temporary_file.name
            writer = csv.DictWriter(temporary_file, fieldnames=OUTPUT_HEADERS)
            writer.writeheader()
            for row in rows:
                team_key = row["team_key"]
                writer.writerow(
                    {
                        "email_address": row["email"],
                        "company": teams[team_key].name,
                        "workspace_id": assignments[team_key],
                    }
                )
        os.replace(temporary_name, output_path)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()


def validate_provisioning_csv(path: Path) -> tuple[int, int, dict[str, int]]:
    """Validate the provisioning contract and return user, team, and load counts."""
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        headers = reader.fieldnames or []
        if headers != OUTPUT_HEADERS:
            raise RosterError(
                f"CSV headers must be exactly {OUTPUT_HEADERS}; got {headers}"
            )

        seen_emails: dict[str, tuple[str, str]] = {}
        workspace_by_team: dict[str, str] = {}
        workspace_counts: dict[str, int] = defaultdict(int)
        row_count = 0

        for line_number, row in enumerate(reader, start=2):
            row_count += 1
            email = (row.get("email_address") or "").strip().lower()
            company = (row.get("company") or "").strip()
            raw_workspace_id = (row.get("workspace_id") or "").strip()
            if not EMAIL_PATTERN.fullmatch(email):
                raise RosterError(
                    f"Invalid email_address on line {line_number}: {email!r}"
                )
            if not company:
                raise RosterError(f"company is required on line {line_number}")
            workspace_id = parse_workspace_id(raw_workspace_id)
            team_key = company.casefold()

            previous_workspace = workspace_by_team.get(team_key)
            if previous_workspace and previous_workspace != workspace_id:
                raise RosterError(
                    f"Team {company!r} spans workspaces "
                    f"{previous_workspace} and {workspace_id}"
                )
            workspace_by_team.setdefault(team_key, workspace_id)

            assignment = (team_key, workspace_id)
            previous_assignment = seen_emails.get(email)
            if previous_assignment and previous_assignment != assignment:
                raise RosterError(
                    f"User {email!r} is assigned to multiple teams or workspaces"
                )
            if previous_assignment:
                raise RosterError(
                    f"Duplicate email_address on line {line_number}: {email!r}"
                )
            seen_emails[email] = assignment
            workspace_counts[workspace_id] += 1

    if not row_count:
        raise RosterError("CSV must contain at least one participant")
    return len(seen_emails), len(workspace_by_team), dict(workspace_counts)


def print_assignment_summary(workspaces: list[Workspace]) -> None:
    """Print a stable, human-readable assignment report."""
    for workspace in workspaces:
        print(
            f"Workspace {workspace.workspace_id}: "
            f"{workspace.member_count} members, {len(workspace.teams)} teams"
        )
        for team in sorted(workspace.teams, key=lambda value: value.name.casefold()):
            print(f"  {team.name}: {len(team.members)}")


def run_assign(args: argparse.Namespace) -> None:
    source_path = Path(args.input).expanduser().resolve()
    if not source_path.is_file():
        raise RosterError(f"Source roster does not exist: {source_path}")

    workspace_ids: list[str] = []
    for raw_workspace in args.workspace:
        workspace_id = parse_workspace_id(raw_workspace)
        if workspace_id not in workspace_ids:
            workspace_ids.append(workspace_id)
    if not workspace_ids:
        raise RosterError("Supply at least one workspace with --workspace")

    rows, teams, email_column, team_column, duplicate_count = load_roster(
        source_path, args.email_column, args.team_column
    )
    pinned = parse_pinned_assignments(args.assignment, teams, workspace_ids)
    assignments, workspaces = assign_teams(teams, workspace_ids, pinned)

    print(f"Source columns: email={email_column!r}, team={team_column!r}")
    print(f"Participants: {len(rows)}; teams: {len(teams)}")
    if duplicate_count:
        print(f"Removed exact duplicate roster rows: {duplicate_count}")
    print_assignment_summary(workspaces)

    if args.dry_run:
        print("Dry run: no file written")
        return

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else source_path.with_name(f"{source_path.stem}_assigned.csv")
    )
    write_output(output_path, source_path, rows, teams, assignments)
    user_count, team_count, workspace_counts = validate_provisioning_csv(output_path)
    print(f"Wrote: {output_path}")
    print(
        f"Validated: {user_count} members, {team_count} teams, "
        f"workspace counts={workspace_counts}"
    )


def run_validate(args: argparse.Namespace) -> None:
    path = Path(args.csv).expanduser().resolve()
    if not path.is_file():
        raise RosterError(f"CSV does not exist: {path}")
    user_count, team_count, workspace_counts = validate_provisioning_csv(path)
    print(f"Valid: {path}")
    print(
        f"Members: {user_count}; teams: {team_count}; "
        f"workspace counts={workspace_counts}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assign whole hackathon teams to Databricks workspaces."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    assign_parser = subparsers.add_parser(
        "assign", help="Balance teams and optionally write a provisioning CSV"
    )
    assign_parser.add_argument("input", help="Source participant roster CSV")
    assign_parser.add_argument(
        "--workspace",
        action="append",
        required=True,
        help="Databricks workspace ID or URL; repeat for each workspace",
    )
    assign_parser.add_argument("--output", help="Output CSV path")
    assign_parser.add_argument("--email-column", help="Source email column")
    assign_parser.add_argument("--team-column", help="Source team column")
    assign_parser.add_argument(
        "--assignment",
        action="append",
        default=[],
        help="Pin a team with TEAM=WORKSPACE; repeat as needed",
    )
    assign_parser.add_argument(
        "--dry-run", action="store_true", help="Print assignments without writing"
    )
    assign_parser.set_defaults(handler=run_assign)

    validate_parser = subparsers.add_parser(
        "validate", help="Validate an existing provisioning CSV"
    )
    validate_parser.add_argument("csv", help="Provisioning CSV to validate")
    validate_parser.set_defaults(handler=run_validate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.handler(args)
    except (OSError, csv.Error, RosterError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
