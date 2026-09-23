# Hackathon Help Desk

Databricks App for hackathon participants to report and track technical issues. It uses React, Express, AppKit, and the existing Lakebase Autoscaling database.

## Features

- Participant identity from Databricks Apps authentication
- Service-principal Lakebase access with authenticated end-user attribution
- Automatic workspace ID plus company, category, priority, and assignee capture
- Shared issue queue with status workflow, search, and filtering
- Comments and activity history
- Seeded dashboard data for demonstrations

## Development

```bash
npm ci
npm run typecheck
npm test
npm run build
```

The deployed app resource supplies the Postgres connection settings. `LAKEBASE_ENDPOINT` is injected from the `postgres` resource in `app.yaml`.

## Deployment

The Databricks App identifier remains `example-app` because app identifiers cannot be renamed. The product name is **Hackathon Help Desk**.

```bash
databricks sync . /Workspace/Users/rob.bajra@databricks.com/hackathon-issue-tracker \
  --exclude node_modules --exclude .git --profile hackathon-workspace-3
databricks apps deploy hackathon-help-desk \
  --source-code-path /Workspace/Users/rob.bajra@databricks.com/hackathon-issue-tracker \
  --profile hackathon-workspace-3
```

The app uses its service principal through the existing `postgres` app resource attached to `projects/rob-project/branches/production`. Databricks Apps supplies the signed-in participant identity for reporter, comment, and activity attribution.
