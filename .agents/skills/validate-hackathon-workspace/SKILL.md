---
name: validate-hackathon-workspace
description: Audit and complete a newly created Databricks hackathon workspace, including administrator access, users, team groups, schemas, cross-team isolation, expected workspace resources, and per-user Git folders. Use for post-creation readiness checks or targeted remediation when workspace IDs, catalogs, schemas, or team rosters vary.
---

# Validate Hackathon Workspace

Establish the expected state, inspect the live account and workspace, populate authorized missing resources, and then verify the final state. Report evidence for every check; a successful provisioning job is not itself proof that access is isolated.

Read [references/verification-matrix.md](references/verification-matrix.md) before running checks. It defines the evidence and pass criteria.

## Resolve the inputs

Reuse details already supplied and discover safe values where possible. Ask one concise, grouped set of questions for anything still missing:

- Databricks account profile or account host and account ID; target workspace profile or host and workspace ID. A host alone is not proof of the workspace ID.
- Expected administrators. Distinguish account-admin users/service principals from an admin group such as `workshop_admins`, and clarify whether each should have `ADMIN` on every account workspace or only the new workspace.
- Expected user-to-team roster. Prefer a CSV with `email_address,company`, but accept an equivalent table. Confirm whether a user may belong to more than one team.
- Catalog and the exact team-group-to-schema mapping. If the user wants names derived from team names, show the proposed mapping and resolve collisions before using it. Never assume the default catalog or schema sanitizer.
- A SQL warehouse and, for runtime isolation tests, a credential/profile for one representative non-admin user per team. Do not request raw tokens in chat.
- Expected Git repository URL, provider, branch or tag, and destination path pattern. Also ask what “workspace resources” includes and obtain an expected-resource manifest: resource type, source or definition, destination/name, owning principal, and allowed team principals.
- Whether this invocation is audit-only or may remediate/populate missing items. If unspecified, audit first and ask before changing live state.

If the user cannot provide an expected roster, schema mapping, or resource manifest, continue with discoverable checks but mark the affected completeness checks `NOT PROVEN`; do not treat whatever currently exists as the intended state.

## Bind credentials to the target

1. Validate both account-level and workspace-level authentication without printing tokens or secret values.
2. Resolve the workspace host and ID from the authenticated workspace client, and independently locate that ID in the account workspace inventory.
3. Stop on a host/ID/profile mismatch. Include the resolved account, workspace ID, host, cloud/region when available, and authenticated principal in the report.
4. Use an account-admin context for account identities and workspace assignments, a workspace-admin context for workspace resources and ACLs, and SQL credentials with metadata visibility for Unity Catalog grants. Use representative-user credentials only for that user's negative tests.

## Build expected state

Normalize email matching case-insensitively while preserving original team and principal names. Reject or ask about duplicate users assigned inconsistently, duplicate team names that differ only by case, and multiple teams mapped to the same schema. Record:

- administrators and required workspace access;
- users, their team groups, workspace assignment, and required entitlements;
- each team group's catalog and schema;
- expected workspace objects and ACLs;
- each user's expected Git folder, repository, and ref.

The expected-state model drives all completeness checks. Do not infer expected users or teams solely from live state.

## Audit before changing anything

Collect read-only evidence for the full matrix:

- List all account workspaces, administrators, account users, account groups, nested group membership, and workspace permission assignments.
- Confirm expected users are active, synced into the target workspace, assigned `USER` or `ADMIN` as intended, and receive `workspace-access` through a direct or group path. Check optional entitlements such as `databricks-sql-access` only when required.
- Confirm each expected team group exists and has exactly the expected roster after accounting for nested membership. Unexpected cross-team membership is an isolation failure, not just a warning.
- Inventory the target catalogs and schemas. Inspect catalog-, schema-, and object-level grants plus ownership for every direct and inherited principal relevant to each user.
- Inventory the in-scope workspace resources and their ACLs. Include home directories and Git folders; include jobs, pipelines, clusters/policies, warehouses, apps, dashboards, or other objects only when the resource manifest puts them in scope.

Unity Catalog permissions are additive. Compute effective access from direct user grants, every nested group, broad groups such as `account users`, ownership, and inherited privileges. Checking only the namesake team group's grants is insufficient.

## Verify isolation

For each team, verify both sides of the boundary:

1. The team can discover and manage its own schema and expected resources.
2. No non-admin membership or ACL path exposes another team's schema or workspace resources.
3. Catalog-wide `BROWSE`, `MANAGE`, `READ METADATA`, ownership, or other broad grants do not defeat schema isolation. `USE CATALOG` alone is expected and is not cross-team schema access.
4. With each representative team user's profile, run read-only positive checks against the user's own schema and negative checks against another team's schema and resources. Account for expected system objects such as `information_schema` explicitly.

Do not create or alter an object in another team's schema merely to test denial. Prove write isolation from effective privileges by default. If the user explicitly requests a live write-denial canary, agree on disposable names and cleanup first; report and remove any canary that unexpectedly succeeds.

An admin-side grant/ACL analysis without representative-user tests can establish configuration correctness but not end-to-end runtime behavior. Mark the runtime row `NOT PROVEN`, rather than `PASS`, when user credentials or a safe test target are unavailable.

## Populate or remediate

Show the proposed changes and their exact targets before live mutation. Make the smallest idempotent change that reaches the expected state, then re-audit affected and downstream checks.

This repository's preferred provisioning path is `admin/jobs`, whose `add-hackathon-account-users` job supports `csv_path`, `catalog`, `schema_owner_group`, `grant_databricks_sql_access`, `provision_git_folders`, and `provision_company_schemas`. It provisions account users, team groups and membership, target-workspace assignments, team entitlements, per-team schemas, and per-user Git folders.

When using that job:

1. Inspect the current source and bundle configuration rather than relying on remembered defaults.
2. Verify the bundle's resolved host and the job's runtime workspace ID equal the target. The committed bundle may name a different workspace.
3. Verify the hard-coded or configured repository URL, branch, and folder convention match the expected Git state.
4. Run and review `run_live=false` first. Do not proceed if the dry run targets unexpected principals, catalogs, schemas, or paths.
5. Run with `run_live=true` only after live execution is authorized, monitor every task, and retain the run ID and task results as evidence.

The job does not prove every administrator has access to every account workspace, and it is not a generic workspace-resource deployer. Fix missing admin assignments through the account Workspace Assignment API. Populate other declared resources through their native Databricks APIs or their existing deployment definitions, applying only the manifest's owner and ACLs. Do not broaden grants to make a deployment succeed.

If the existing job cannot represent the requested schema mapping, Git source/ref, resource manifest, or target workspace safely, stop and present the smallest required code/configuration change instead of silently substituting defaults.

## Reconcile and report

Allow bounded time for account-to-workspace identity synchronization after mutations, then repeat all checks. Use `PASS`, `FAIL`, or `NOT PROVEN` exactly as defined in the reference. Lead with overall readiness, list failures and gaps with affected principals/resources, identify all mutations and run IDs, and include concise evidence that can be rerun without exposing credentials.
