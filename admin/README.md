# Admin jobs

The jobs in [`jobs/`](jobs/) clean up Databricks account identities after the
hackathon. They are deployed together as the
`hackathon-account-identity-cleanup` Databricks Asset Bundle, but each job can
be run independently.

All three jobs are destructive only when the `run_live` job parameter is set to
`true`. Its default is `false`, which produces a dry-run report of the objects
that would be deleted. Review a successful dry run before starting a live run.

## Jobs and their roles

### `remove-non-admin-account-users`

Removes every account user that does not have the `account_admin` role. It also
removes non-admin and orphaned directories under `/Users` in the workspace,
while preserving directories belonging to account admins. Protected workspace
directories that Databricks refuses to remove are reported and skipped.

Use this job to remove participant user accounts and their workspace content
after the event. Because workspace directories are deleted recursively in live
mode, inspect both the user and directory lists in the dry-run output.

- Definition: [`jobs/resources/remove-users.job.yml`](jobs/resources/remove-users.job.yml)
- Notebook: [`jobs/notebooks/remove_users.py`](jobs/notebooks/remove_users.py)

### `remove-non-admin-account-service-principals`

Removes every account service principal that does not have the `account_admin`
role. Account-admin service principals are preserved so automation and account
administration can continue.

Use this job to remove service principals created by hackathon projects without
deleting the administrative identity used to perform cleanup.

- Definition: [`jobs/resources/remove-service-principals.job.yml`](jobs/resources/remove-service-principals.job.yml)
- Notebook: [`jobs/notebooks/remove_service_principals.py`](jobs/notebooks/remove_service_principals.py)

### `remove-unprotected-account-groups`

Removes account groups except for this explicit protected set:

- `account users`
- `workshop_admins`
- `workshop_users`

Group-name comparisons ignore case and surrounding whitespace. As a safety
check, the job stops without deleting anything if any protected group is
missing from the account.

Use this job to remove temporary or participant-created groups while retaining
the baseline groups required by the workshop environment.

- Definition: [`jobs/resources/remove-groups.job.yml`](jobs/resources/remove-groups.job.yml)
- Notebook: [`jobs/notebooks/remove_groups.py`](jobs/notebooks/remove_groups.py)

## Shared configuration

The jobs authenticate to the Databricks account with an account-admin service
principal. Bundle variables in [`jobs/databricks.yml`](jobs/databricks.yml)
identify the account host and the workspace secret scope and keys containing:

- the Databricks account ID;
- the admin service principal client ID; and
- the admin service principal client secret.

The default secret scope is `hackathon-admin`. Secrets are read at runtime and
are not stored in the bundle.

## Recommended cleanup order

Run each job in dry-run mode first. After reviewing its output, rerun it with
`run_live=true`. A practical live cleanup order is users, service principals,
then groups; this makes the increasingly broad identity cleanup easy to review
in separate runs.
