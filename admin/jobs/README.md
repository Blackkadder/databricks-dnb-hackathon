# Account administration jobs

## Add hackathon users

The `add-hackathon-account-users` job reads a CSV from a Unity Catalog volume.
The file must have exactly these headers:

```csv
email_address,company,workspace_id
person@example.com,Example Company,1234567890123456
other@example.com,Another Company,9876543210987654
```

The same CSV can be used by jobs deployed to multiple workspaces. Each job gets
the ID of the workspace in which it is running and provisions only rows whose
`workspace_id` matches. Rows for other workspaces are validated but skipped.
The `workspace_id` must be a positive integer, and a company (team) may be
assigned to only one workspace across the entire file. If no rows match the
current workspace, both tasks exit successfully without making changes.

For each matching row, the job idempotently:

1. creates the account-level user if needed;
2. creates or reuses an account group whose name exactly matches `company`;
3. adds the user to that group, grants the group and user `USER` access to the
   current workspace, and explicitly grants the company group `workspace-access`;
4. creates `/Users/<email>/databricks-dnb-hackathon` from the `develop` branch; and
5. grants that user `CAN_MANAGE` on their Git folder.

The job dry-runs by default. Upload the CSV, then run it once with its
default `csv_path` of
`/Volumes/admin/workshop_provisioning/user_provisioning/users.csv`. Review the
output before running it again with `run_live=true`.

The `grant_databricks_sql_access` parameter defaults to `true`, which also
grants each company group `databricks-sql-access`. Set it to `false` when
participants should have workspace authoring access without Databricks SQL.

Set `provision_git_folders=false` to provision identities, entitlements, and
schemas without creating per-user Git folders. This is useful when the external
Git provider or the Databricks Git-folder service is temporarily unavailable.

Set `provision_company_schemas=false` for an identity-only run when the supplied
catalog is not available. The schema task exits successfully without executing
any catalog statements.

### Per-company schemas

After users are provisioned, the `create_company_schemas` task (which depends
on the provisioning task) applies the same workspace filter, creates one Unity
Catalog schema per matching distinct company, and grants that company's account
group full access to it. For each company it:

1. derives a schema name by sanitizing the company (lowercased, with each run of
   non-alphanumeric characters replaced by `_`), so `Life360` becomes `life360`;
2. limits both `account users` and the company group to `USE CATALOG` at the
   catalog level, removing grants such as `BROWSE` that expose other schemas;
3. runs `CREATE SCHEMA IF NOT EXISTS <catalog>.<schema>`;
4. grants the company group `ALL PRIVILEGES` and explicit `MANAGE` on that
   schema; and
5. transfers the schema's ownership to the configured owner principal (`ALTER
   SCHEMA ... OWNER TO`).

Because grants target the company account group, membership changes propagate
automatically. The catalog is set by the `catalog` job parameter, which defaults
to `databricks-hackathon` and is assumed to already exist. The owner principal
is set by the `schema_owner_group` job parameter, which defaults to
`rob.bajra@databricks.com`.
If two different company strings sanitize to the same schema name, the task
fails rather than merging them. This task honors `run_live`: the dry run prints
the `REVOKE`, `GRANT`, `CREATE SCHEMA`, and `ALTER SCHEMA` statements it would
run and changes nothing.

The task removes catalog-level `ALL PRIVILEGES`, `BROWSE`, `MANAGE`, and
`READ METADATA` from `account users` and each company group, then grants only
`USE CATALOG`. Because Unity Catalog privileges are additive, users who belong
to some other group with broader access to `databricks-hackathon` can still
inherit that access. The built-in `information_schema` might also remain visible.

The job's run-as identity must own the catalog or have `MANAGE` on it so it can
normalize catalog grants, must be able to create schemas, and must be allowed
to transfer ownership to `schema_owner_group`. Re-runs remain idempotent.
`MANAGE` is granted separately on each namesake schema because Unity Catalog
does not include it in `ALL PRIVILEGES`.

### User invitation emails

The job creates users through the [Account SCIM Users API][account-user-api]
and grants workspace access through the Workspace Assignment API. It does not
call an email or notification API, and the Account Users API has no
invitation-notification option. The [Databricks user-management docs][users-doc]
explicitly promise a confirmation email when a workspace admin adds a new user
through **Settings > Identity and access > Users > Add user > Add new**; they do
not make that promise for the SCIM/API flow used here. Do not rely on this job
to send invitations. Send participants the workspace URL and sign-in
instructions separately, or add an explicit notification step outside
Databricks identity provisioning.

[account-user-api]: https://docs.databricks.com/api/scim/v1/create-account-user
[users-doc]: https://docs.databricks.com/aws/en/admin/users-groups/users

Deploy from this directory:

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
```
