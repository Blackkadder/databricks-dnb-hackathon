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

Deploy from this directory:

```bash
databricks bundle validate -t dev
databricks bundle deploy -t dev
```
