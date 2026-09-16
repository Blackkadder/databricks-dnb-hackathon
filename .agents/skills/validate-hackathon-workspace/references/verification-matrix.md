# Verification Matrix

Use this matrix for both the pre-change audit and final report.

## Status rules

- `PASS`: the expected state and required authorization boundary were directly evidenced.
- `FAIL`: observed state contradicts the expected state, including an unexpected principal, inherited grant, or resource ACL.
- `NOT PROVEN`: required input, visibility, credentials, resource scope, or runtime evidence is unavailable. Never convert this to `PASS` because no failure was observed.

Record the command, API/SQL operation, or returned object identifiers used as evidence, but redact tokens, secrets, and sensitive response fields.

## Checks

| Check | Required evidence | PASS criteria |
|---|---|---|
| Target binding | Authenticated workspace host and principal; workspace client's reported ID; matching account workspace inventory record | All identifiers resolve to the intended active workspace |
| Admins have access to all required workspaces | Expected admin set; complete account workspace inventory; Workspace Assignment API results for every admin/workspace pair | Every required pair has `ADMIN`; no workspace is silently omitted |
| Users are added | Expected roster; account SCIM users; target workspace SCIM users; workspace assignments; effective entitlements | Every expected user is active, synced, has intended `USER`/`ADMIN`, and has `workspace-access`; optional entitlements match policy |
| Team groups are complete | Expected team roster; account groups; recursively expanded membership; target workspace groups | Every expected group exists and contains exactly the intended users; no user receives unintended team access through nesting |
| Team schemas are complete | Exact catalog/schema mapping; schema inventory; schema owner | Every mapped schema exists in the intended catalog and has the intended stable owner |
| Team can manage its own schema | Catalog, schema, and relevant object grants for the user and all effective groups; representative-user positive metadata check | Effective access includes `USE CATALOG`, `USE SCHEMA`, explicit `MANAGE`, and the requested data/DDL privileges; own-schema runtime check succeeds |
| Team cannot see/change another schema | Direct and inherited membership; catalog/schema/object grants and ownership; representative-user negative metadata/read checks | No effective path supplies cross-team discovery, use, read, create, modify, manage, or ownership. Runtime access is denied except documented system objects |
| Workspace resources are populated | User-approved expected-resource manifest; resource inventory; source/version or deployment identity; owner and ACLs | Every expected resource exists at the intended version/location and its owner/ACL matches the manifest |
| Workspace resources are isolated | Recursive memberships; object ACLs for every in-scope resource; representative-user positive/negative access checks where APIs permit | Intended team can use/manage its resources; other non-admin teams have no view/use/change path; only declared admin access remains |
| Git folders are populated and isolated | Expected URL/provider/ref/path; Repos/Git Folders API; object permissions; representative-user access check | Each expected folder exists at the exact path, points to the expected repository/ref, the user/team has intended permission, and unrelated teams have no access |

## Effective Unity Catalog access

Evaluate access per user, not just per named team group:

1. Expand direct and nested account-group membership, including broad default groups.
2. Collect applicable catalog, schema, and object privileges and ownership for the user and every effective group.
3. Treat privileges as additive. A correct team-group grant does not cancel a broad grant inherited elsewhere.
4. On the shared catalog, flag cross-team exposure from privileges such as `BROWSE`, `READ METADATA`, `MANAGE`, ownership, or broad data privileges. `USE CATALOG` by itself is compatible with isolation.
5. On another team's schema and objects, flag `USE SCHEMA`, `MANAGE`, ownership, create/modify privileges, read privileges, or `ALL PRIVILEGES` from any path.
6. Distinguish grants on existing objects from future-object behavior and ownership. Note any untested resource type rather than generalizing from schema grants.

For the repository's current provisioning model, a typical intended state is:

- `account users`: `USE CATALOG` only on the shared catalog;
- each team group: `USE CATALOG` on the shared catalog, plus `ALL PRIVILEGES` and explicit `MANAGE` on its own schema;
- stable admin group: schema owner;
- no team principal: catalog-wide `BROWSE`, `MANAGE`, or `READ METADATA`.

This is a reference shape, not a source of catalog, schema, or principal names. Compare against the user's confirmed mapping.

## Representative-user runtime checks

Use at least one non-admin user per team when credentials are available. Keep tests read-only unless the user separately approves a canary.

- Confirm current identity and target workspace first.
- List schemas in the shared catalog. Expect only authorized schemas plus documented system schemas.
- Describe the user's own schema and list its objects; this must succeed.
- Try to describe or list objects in a different team's schema by exact name; access should be denied or reveal no objects according to the intended policy.
- Try a zero-row or metadata-only read of a known disposable object in another team's schema when one is supplied; it must be denied.
- List/get the user's own declared workspace resources and Git folder; this must succeed.
- Try list/get on another team's declared paths or objects by exact identifier; it must be denied.

Do not interpret an invalid object name, missing object, wrong warehouse, or authentication error as an authorization denial. Capture the authorization-specific response.

## Report shape

Start with:

```text
Overall readiness: PASS | FAIL | NOT PROVEN
Target: <workspace host> (workspace ID <id>, account <id>)
Authenticated as: <admin principal>
Expected: <user count> users, <team count> teams, <resource count> resources
```

Then provide the matrix with `Check`, `Status`, `Evidence`, and `Issue/remediation`. Add:

- unexpected users, memberships, grants, schemas, or ACLs that affect isolation;
- mutations performed, exact targets, job/run IDs, and final outcomes;
- tests not run and the specific input or credential needed;
- a short rerun recipe using identifiers rather than secrets.

Overall readiness is `FAIL` if any required row fails. It is `NOT PROVEN` if nothing fails but any required row is not proven. It is `PASS` only when every required row passes.
