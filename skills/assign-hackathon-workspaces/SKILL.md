---
name: assign-hackathon-workspaces
description: Convert hackathon participant rosters into validated Databricks provisioning CSVs while keeping each team in one workspace and balancing participants across the supplied workspaces. Use when preparing, assigning, or checking team-to-workspace roster files for hackathon provisioning.
---

# Assign Hackathon Workspaces

Create a new provisioning CSV without modifying the source roster. This skill prepares local files only. Do not upload the CSV or provision users unless the user separately requests those actions.

## Required inputs

- A participant roster CSV.
- One or more Databricks workspace IDs or workspace URLs. For a URL, use the numeric `o` query parameter as the workspace ID.
- The email and team columns when the headers are unusual.

The helper detects common email headers such as `Email` and `email_address`. It prefers `Team` over `company` or `Organization` because provisioning groups represent hackathon teams. Override detection when the source uses a different meaning.

## Assignment workflow

1. Inspect the roster headers and confirm which columns represent email and team. Do not use a participant's employer as `company` when a separate team column exists.
2. If the user asks for a proposal or plan, run the helper with `--dry-run` and report the proposed team mapping and participant totals before writing a file.
3. If the user asks to create the assigned roster, run the helper without `--dry-run`. By default it writes `<source-stem>_assigned.csv` beside the source.
4. Run the helper's `validate` command on the output.
5. Report the output path, member and team counts, workspace totals, and whether every team has exactly one workspace.

The assignment is deterministic. It places larger teams first into the workspace with the fewest assigned participants, then the fewest assigned teams, then the earliest workspace argument. This balances people without splitting teams. Repeated `--assignment 'Team=workspace'` options pin requested teams before the remaining teams are balanced.

## Commands

From this skill directory:

```bash
python3 scripts/assign_workspaces.py assign /path/to/roster.csv \
  --workspace 'https://dbc-example.cloud.databricks.com/?o=123' \
  --workspace 456 \
  --dry-run
```

Create the file after the mapping is accepted:

```bash
python3 scripts/assign_workspaces.py assign /path/to/roster.csv \
  --workspace 123 \
  --workspace 456

python3 scripts/assign_workspaces.py validate \
  /path/to/roster_assigned.csv
```

Use `--email-column` or `--team-column` to override header detection, `--output` to choose a different output path, and `--assignment 'Team=123'` to preserve a requested team placement.

## Output contract

The output must have exactly these columns in this order:

```csv
email_address,company,workspace_id
```

Emails are normalized to lowercase, exact duplicate roster entries are removed, workspace IDs are positive integers, and team matching is case-insensitive. A member cannot belong to multiple teams or workspaces, and a team cannot span workspaces. The output is compatible with the repository's [provisioning CSV validator](../../admin/jobs/notebooks/provisioning_csv.py).
