# Account administration jobs

## Add hackathon users

The `add-hackathon-account-users` job reads a CSV from a Unity Catalog volume.
The file must have exactly these headers:

```csv
email_address,company
person@example.com,Example Company
```

For each row, the job idempotently:

1. creates the account-level user if needed;
2. creates or reuses an account group whose name exactly matches `company`;
3. adds the user to that group and grants the group and user `USER` access to the current workspace;
4. creates `/Users/<email>/databricks-dnb-hackathon` from the `develop` branch; and
5. grants that user `CAN_MANAGE` on their Git folder.

The job dry-runs by default. Upload the CSV, then run it once with its
default `csv_path` of
`/Volumes/admin/workshop_provisioning/user_provisioning/users.csv`. Review the
output before running it again with `run_live=true`.

### Per-company schemas

After users are provisioned, the `create_company_schemas` task (which depends
on the provisioning task) creates one Unity Catalog schema per distinct company
and grants that company's account group full access to it. For each company it:

1. derives a schema name by sanitizing the company (lowercased, with each run of
   non-alphanumeric characters replaced by `_`), so `Life360` becomes `life360`;
2. runs `CREATE SCHEMA IF NOT EXISTS <catalog>.<schema>`;
3. grants the company group `ALL PRIVILEGES` on that schema; and
4. transfers the schema's ownership to a stable admin group (`ALTER SCHEMA ...
   OWNER TO`) so schemas are not tied to the individual that ran the job.

Because grants target the company account group, membership changes propagate
automatically. The catalog is set by the `catalog` job parameter, which defaults
to `lakebase_hackathon` and is assumed to already exist. The owner group is set
by the `schema_owner_group` job parameter, which defaults to `workshop_admins`.
If two different company strings sanitize to the same schema name, the task
fails rather than merging them. This task honors `run_live`: the dry run prints
the `CREATE SCHEMA`, `GRANT`, and `ALTER SCHEMA` statements it would run and
changes nothing.

Catalog traversal (`USE CATALOG`) is expected to come from the account-wide
`account users` grant that already exists on the catalog, so the task issues no
catalog-level grant. The job's run-as identity needs to be able to create
schemas in the catalog (for example `ALL PRIVILEGES`, or `CREATE SCHEMA` +
`USE CATALOG`, or catalog ownership) and to be a **member of
`schema_owner_group`** so it can transfer ownership. It does not need `MANAGE` on
the catalog, because the run-as identity owns each schema it creates and can
grant on it directly. Note that `ALL PRIVILEGES` does not include `MANAGE`.
Re-runs stay idempotent: once ownership belongs to the group, a run-as identity
that is a member of that group can still re-run the grant and the ownership
transfer as no-ops.

Deploy from this directory:

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
```
