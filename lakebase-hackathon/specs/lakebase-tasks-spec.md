<!--
Copyright 2026 Databricks, Inc.
SPDX-License-Identifier: Apache-2.0
-->

# Lakebase: Hands-On Learning Plan

> **Role:** This is the **hands-on learning companion** — module-by-module walkthroughs
> with runnable SQL / CLI / SDK. The formal **contract** (deliverables, tests, acceptance)
> is [`lakebase-hackathon-spec.md`](./lakebase-hackathon-spec.md); when the two disagree, the
> contract wins.

> **Context:** Lakebase is Neon-derived Postgres (copy-on-write storage,
> safekeepers/pageservers, scale-to-zero, branching) wrapped in the Databricks control
> plane + Unity Catalog. For a PostgreSQL/DBaaS background this maps almost 1:1 — the
> novel parts are the **hierarchical resource model**, **OAuth token auth**, and **UC
> integration**. Neon/Postgres parallels are flagged throughout.

---

## Module 0 — Prerequisites

- FE-VM **serverless** workspace (use `/databricks-fe-vm-workspace-deployment`)
- Databricks CLI **≥ 0.285.0** (`databricks --version`) — Autoscaling requires this
- Authenticate: `databricks auth login --host <workspace-url> --profile <profile>`
- `psql` client: `brew install postgresql@16`
- Python SDK: `pip install -U "databricks-sdk>=0.81.0" "psycopg[binary]>=3.0" sqlalchemy`

**Resource hierarchy to internalize:**

```
Project (e.g., projects/mylakebase)
  └── Branch (e.g., .../branches/production)
       └── Endpoint / compute (e.g., .../endpoints/primary)
Inside a branch: Database → Schema
```

Creating a project auto-creates a `production` branch + `primary` R/W endpoint +
`databricks_postgres` database.

---

## Module 1 — Create, Authenticate, Connect, Build Objects

**Goal:** Get from zero to a running app-connected database.

### 1a. Create via UI
Workspace → **Compute → Database instances** (Lakebase section) → create project.
Note the auto-created production branch and primary endpoint, and how the UI surfaces
host, CU range, and scale-to-zero timeout.

### 1b. Create via code

CLI:
```bash
databricks postgres create-project mylakebase \
  --json '{"spec": {"display_name": "Lakebase Lab", "pg_version": "18"}}' -p PROFILE
```

SDK:
```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.postgres import Project, ProjectSpec

w = WorkspaceClient()
w.postgres.create_project(
    project=Project(spec=ProjectSpec(display_name="Lakebase Lab", pg_version="18")),
    project_id="mylakebase").wait()
```

Verify branch state = READY and endpoint state = ACTIVE:
```bash
databricks postgres list-branches projects/mylakebase -p PROFILE -o json \
  | jq '.[].status.current_state'
databricks postgres list-endpoints projects/mylakebase/branches/production -p PROFILE -o json \
  | jq '.[].status.current_state'
```

### 1c. Authenticate — the key mental shift
- Auth = **OAuth token as the Postgres password**, user = your Databricks email,
  tokens expire in **1 hour**.
- Also learn **native Postgres passwords** (no expiry) for tools that can't rotate tokens.

```bash
HOST=$(databricks postgres list-endpoints projects/mylakebase/branches/production \
  -p PROFILE -o json | jq -r '.[0].status.hosts.host')
TOKEN=$(databricks postgres generate-database-credential \
  projects/mylakebase/branches/production/endpoints/primary -p PROFILE -o json | jq -r '.token')
EMAIL=$(databricks current-user me -p PROFILE -o json | jq -r '.userName')

PGPASSWORD=$TOKEN psql "host=$HOST port=5432 dbname=databricks_postgres user=$EMAIL sslmode=require" \
  -c "SELECT version();"
```

### 1d. Initialize the dataset — NYC Taxi + PostGIS
`CREATE DATABASE` first (the default database's `public` schema is restricted), then
build **one dataset** we'll use for the rest of the curriculum: a **NYC Taxi + PostGIS
5-table star schema**. This doubles as proof that **Lakebase is genuinely 100% standard
Postgres** — the stock PostGIS extension, ordinary DDL, foreign keys, and GIST indexes
all work verbatim.

> **100% Postgres:** Lakebase ships 40+ standard extensions (`postgis`, `postgis_raster`,
> `postgis_topology`, `pgrouting`, `vector`, `pgcrypto`, `uuid-ossp`, …), installed with
> plain `CREATE EXTENSION`. See
> [Lakebase Postgres extensions](https://docs.databricks.com/aws/en/oltp/projects/extensions).
> Enabling PostGIS needs no special API — it's the same command you'd run on vanilla
> Postgres or RDS.

```bash
# Dedicated database (the default DB's public schema is restricted)
PGPASSWORD=$TOKEN psql "host=$HOST port=5432 dbname=postgres user=$EMAIL sslmode=require" \
  -c "CREATE DATABASE nyc_taxi;"
```

**Schema (DDL)** — run against `dbname=nyc_taxi`:
```sql
-- Prove it's real Postgres: enable the stock PostGIS extension.
CREATE EXTENSION IF NOT EXISTS postgis;
-- Standard Postgres catalogs work unchanged:
--   SELECT * FROM pg_available_extensions WHERE name LIKE 'postgis%';
--   SELECT postgis_full_version();

-- (1) Spatial dimension: NYC TLC taxi zones (263 zones; MultiPolygon geometry)
CREATE TABLE taxi_zones (
    location_id   INT PRIMARY KEY,
    borough       TEXT NOT NULL,
    zone          TEXT NOT NULL,
    service_zone  TEXT,
    geom          geometry(MultiPolygon, 4326)
);
CREATE INDEX idx_taxi_zones_geom ON taxi_zones USING GIST (geom);

-- (2-4) Lookup dimensions (official TLC code sets)
CREATE TABLE vendors (
    vendor_id  INT PRIMARY KEY,
    name       TEXT NOT NULL
);
CREATE TABLE rate_codes (
    rate_code_id INT PRIMARY KEY,
    description  TEXT NOT NULL
);
CREATE TABLE payment_types (
    payment_type INT PRIMARY KEY,
    description  TEXT NOT NULL
);

-- (5) Fact table: individual trips, with pickup/dropoff points + FKs to every dimension
CREATE TABLE trips (
    trip_id             BIGSERIAL PRIMARY KEY,
    vendor_id           INT REFERENCES vendors(vendor_id),
    pickup_datetime     TIMESTAMPTZ NOT NULL,
    dropoff_datetime    TIMESTAMPTZ NOT NULL,
    passenger_count     SMALLINT,
    trip_distance       NUMERIC(8,2),
    pickup_location_id  INT REFERENCES taxi_zones(location_id),
    dropoff_location_id INT REFERENCES taxi_zones(location_id),
    rate_code_id        INT REFERENCES rate_codes(rate_code_id),
    payment_type        INT REFERENCES payment_types(payment_type),
    fare_amount         NUMERIC(8,2),
    tip_amount          NUMERIC(8,2),
    total_amount        NUMERIC(8,2),
    pickup_point        geometry(Point, 4326),
    dropoff_point       geometry(Point, 4326)
);
CREATE INDEX idx_trips_pickup_point  ON trips USING GIST (pickup_point);
CREATE INDEX idx_trips_dropoff_point ON trips USING GIST (dropoff_point);
CREATE INDEX idx_trips_pickup_dt     ON trips (pickup_datetime);
```

**Seed data (INSERT)** — dimensions, a few zones, and sample trips:
```sql
INSERT INTO vendors (vendor_id, name) VALUES
    (1, 'Creative Mobile Technologies'),
    (2, 'VeriFone Inc.');

INSERT INTO rate_codes (rate_code_id, description) VALUES
    (1, 'Standard rate'), (2, 'JFK'), (3, 'Newark'),
    (4, 'Nassau or Westchester'), (5, 'Negotiated fare'), (6, 'Group ride');

INSERT INTO payment_types (payment_type, description) VALUES
    (1, 'Credit card'), (2, 'Cash'), (3, 'No charge'),
    (4, 'Dispute'), (5, 'Unknown'), (6, 'Voided trip');

-- Real zone ids with simplified polygons (WKT); each contains its sample points.
INSERT INTO taxi_zones (location_id, borough, zone, service_zone, geom) VALUES
    (132, 'Queens',    'JFK Airport', 'Airports',
     ST_Multi(ST_GeomFromText('POLYGON((-73.79 40.64,-73.77 40.64,-73.77 40.66,-73.79 40.66,-73.79 40.64))', 4326))),
    (161, 'Manhattan', 'Midtown Center', 'Yellow Zone',
     ST_Multi(ST_GeomFromText('POLYGON((-73.98 40.75,-73.97 40.75,-73.97 40.76,-73.98 40.76,-73.98 40.75))', 4326))),
    (230, 'Manhattan', 'Times Sq/Theatre District', 'Yellow Zone',
     ST_Multi(ST_GeomFromText('POLYGON((-73.99 40.75,-73.98 40.75,-73.98 40.76,-73.99 40.76,-73.99 40.75))', 4326)));

-- Trips: pickup/dropoff captured as PostGIS points via ST_MakePoint(lon, lat).
INSERT INTO trips (vendor_id, pickup_datetime, dropoff_datetime, passenger_count,
                   trip_distance, pickup_location_id, dropoff_location_id,
                   rate_code_id, payment_type, fare_amount, tip_amount, total_amount,
                   pickup_point, dropoff_point) VALUES
    (2, '2026-08-01 08:12:00+00', '2026-08-01 08:47:00+00', 1, 17.6, 132, 161, 2, 1, 70.00, 14.00, 88.80,
     ST_SetSRID(ST_MakePoint(-73.7810, 40.6440), 4326), ST_SetSRID(ST_MakePoint(-73.9760, 40.7555), 4326)),
    (1, '2026-08-01 09:05:00+00', '2026-08-01 09:14:00+00', 2,  1.2, 161, 230, 1, 2,  9.50,  0.00, 11.30,
     ST_SetSRID(ST_MakePoint(-73.9760, 40.7555), 4326), ST_SetSRID(ST_MakePoint(-73.9855, 40.7580), 4326)),
    (2, '2026-08-01 23:40:00+00', '2026-08-01 23:52:00+00', 3,  2.9, 230, 161, 1, 6,  0.00,  0.00,  0.00,
     ST_SetSRID(ST_MakePoint(-73.9855, 40.7580), 4326), ST_SetSRID(ST_MakePoint(-73.9760, 40.7555), 4326)); -- voided
```

### 1e. Perform CRUD on the dataset
Standard Postgres DML plus PostGIS spatial functions — nothing Lakebase-specific.

```sql
-- READ: enrich trips with dimension labels + straight-line distance (meters)
SELECT t.trip_id, v.name AS vendor, pz.zone AS pickup_zone, dz.zone AS dropoff_zone,
       pt.description AS payment, t.total_amount,
       ROUND(ST_DistanceSphere(t.pickup_point, t.dropoff_point)::numeric, 0) AS crow_flies_m
FROM trips t
JOIN vendors       v  ON v.vendor_id     = t.vendor_id
JOIN taxi_zones    pz ON pz.location_id  = t.pickup_location_id
JOIN taxi_zones    dz ON dz.location_id  = t.dropoff_location_id
JOIN payment_types pt ON pt.payment_type = t.payment_type
ORDER BY t.pickup_datetime;

-- READ (spatial predicate): which zone polygon actually contains each pickup point?
SELECT t.trip_id, z.zone
FROM trips t
JOIN taxi_zones z ON ST_Contains(z.geom, t.pickup_point);

-- UPDATE: correct a mis-recorded fare and recompute the total (+ $4.80 taxes/surcharges)
UPDATE trips
SET fare_amount  = 72.50,
    total_amount = 72.50 + tip_amount + 4.80
WHERE trip_id = 1;

-- DELETE: remove voided trips (payment_type 6)
DELETE FROM trips WHERE payment_type = 6;
```

**Milestone (dataset):** `nyc_taxi` initialized on `production` with the 5-table PostGIS
schema, seeded, and CRUD-verified — the single dataset the rest of the modules build on.

### 1f. Connect a Python app
Start simple (psycopg), then adopt the production connection manager (SQLAlchemy engine
+ token refresh at 50 min via a `do_connect` listener that checks token age).

```python
import psycopg
from databricks.sdk import WorkspaceClient

def get_connection(project_id, branch_id="production", endpoint_id="primary",
                   database_name="nyc_taxi"):
    w = WorkspaceClient()
    ep_name = f"projects/{project_id}/branches/{branch_id}/endpoints/{endpoint_id}"
    host = w.postgres.get_endpoint(name=ep_name).status.hosts.host
    token = w.postgres.generate_database_credential(endpoint=ep_name).token
    conn_string = (
        f"host={host} dbname={database_name} "
        f"user={w.current_user.me().user_name} password={token} sslmode=require")
    return psycopg.connect(conn_string)

with get_connection("mylakebase") as conn, conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM trips")
    print(cur.fetchone())
```

**Connection gotchas:** 1-hour token expiry (refresh at 50 min), 24h idle timeout,
3-day max connection life, scale-to-zero wake latency (add retry logic), macOS DNS
`hostaddr` workaround.

**Milestone:** A Python script that reads/writes a table through a pooled,
token-refreshing connection.

> **Two kinds of pooling — don't confuse them:**
> - **App-side pool + OAuth token refresh** *(this module)* — your driver's pool
>   (SQLAlchemy/HikariCP) holds connections to the **direct** endpoint; you refresh the
>   1-hour token on connect. Keeps the secure short-lived-credential model. Use for
>   notebooks and services you control.
> - **Server-side PgBouncer pooler** *(Neon-style)* — Lakebase's built-in transaction-mode
>   pooler, up to 10k client connections, via the
>   `<endpoint-id>-pooler.<region>.<cloud>.databricks.com` host. **Requires a native Postgres
>   *password* role — not available for OAuth roles**, and transaction mode drops session
>   state / `LISTEN`-`NOTIFY` / advisory locks (use a direct connection for `pg_dump` and
>   migrations). Use for many short-lived connections (serverless functions, web APIs).

---

## Module 2 — Branch, Make a Change, Promote

**Goal:** Use DB branching as a dev workflow (Neon-style; not available in Provisioned) —
fork the live `nyc_taxi` dataset, make one isolated schema change, validate it, then
promote it to `production`.

Mental model: branches are **copy-on-write clones** sharing parent storage — instant,
cheap, isolated. Because `nyc_taxi` already lives on `production` (Module 1), the branch
starts with the full dataset for free — no re-seeding.

1. **Branch from production** with a TTL so it auto-cleans:
   ```bash
   databricks postgres create-branch projects/mylakebase feature-x \
     --json '{"spec": {"source_branch": "projects/mylakebase/branches/production", "ttl": "604800s"}}' -p PROFILE
   ```
2. **Add an endpoint** (new branches have none):
   ```bash
   databricks postgres create-endpoint projects/mylakebase/branches/feature-x read-write \
     --json '{"spec": {"endpoint_type": "ENDPOINT_TYPE_READ_WRITE", "autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 2.0}}' -p PROFILE
   ```
3. **Make one simple change on `feature-x`** — add the real NYC TLC `congestion_surcharge`
   column (introduced in 2019) and backfill it. Point `psql` at the branch host; the
   `nyc_taxi` dataset is already present via copy-on-write.
   ```sql
   -- Schema change, isolated to feature-x
   ALTER TABLE trips ADD COLUMN congestion_surcharge NUMERIC(8,2) DEFAULT 0;

   -- Backfill: $2.50 surcharge for trips picked up in Manhattan
   UPDATE trips t
   SET congestion_surcharge = 2.50
   FROM taxi_zones z
   WHERE z.location_id = t.pickup_location_id
     AND z.borough = 'Manhattan';
   ```
4. **Test the change in isolation:**
   ```sql
   -- On feature-x: the column exists and is populated
   SELECT trip_id, total_amount, congestion_surcharge FROM trips ORDER BY trip_id;
   ```
   Run the same query on `production` and confirm it still **errors**
   (`column "congestion_surcharge" does not exist`) — proving the change is confined to
   the branch.
5. **Promote the change — there is NO git-style merge.** You cannot merge a child branch
   back into its parent; the supported pattern is to **promote the *migration*, not the
   branch** ([Branches docs](https://docs.databricks.com/aws/en/oltp/projects/branches)):
   - **Re-apply the validated migration to `production`** — run the same
     `ALTER TABLE … ADD COLUMN` (and backfill) against the parent, ideally via a migration
     tool (Flyway / Alembic / Liquibase) from CI on PR merge, so the exact change proven on
     `feature-x` is what lands. This is the recommended path.
   - **Schema-diff first** (e.g., `pg_dump --schema-only` of both branches, or a schema
     diff tool) to confirm precisely what will change before touching `production`.
   - **`reset` is *not* a merge — it goes the other way.** A branch *reset* refreshes a
     child *from* its parent (parent → child only), discarding the child's changes. It is
     exposed via the **UI and Terraform** (`databricks_postgres_branch`), **not** the
     `databricks postgres` CLI/SDK as of **CLI 0.299.1 / SDK 0.114.0** — so our automation
     never calls it, and it can't be used to push `feature-x` into `production`.
6. **Cleanup:** delete/expire the branch (cascades to endpoints). Limits: **10
   unarchived branches/project**; can't delete default/protected/parent-of-children
   branches.

**Milestone:** `congestion_surcharge` added and backfilled on `feature-x`, verified
isolated from `production`, then promoted by re-applying the migration to the parent, and
the branch retired. Key takeaway — the **merge gap**: you promote migrations, not
branches, a real talking point for customers expecting git-branch semantics.

---

## Module 3 — Point-in-Time Recovery

**Goal:** Recover to any moment in the retention window. PITR in Lakebase = **branch
from past data** (no separate "restore" verb; the branch mechanism IS the restore).

1. **Understand the window:** instant restore up to **35 days** (configurable
   retention). PITR storage billed separately ($0.20/GB-month).
2. **Simulate disaster:** timestamp T0 → run a destructive `UPDATE`/`DROP` → note T1.
3. **Recover:** create a branch with a **past-data source** anchored before T1
   (`source_branch` + `source_branch_time` in the branch spec). Branch creation
   **requires an expiration** — include `ttl` (or `expire_time` / `no_expiry`) or the API
   rejects it. Spin an endpoint, verify good data.
4. **Promote the recovery:** copy corrected data back to production, or repoint the
   app to the recovered branch and re-protect it.
5. **Contrast with vanilla Postgres/RDS:** base-backup + WAL replay PITR vs Lakebase's
   instant copy-on-write restore off pageserver history — no replay.

**Milestone:** Documented recovery runbook: detect → branch-from-timestamp → validate
→ promote.

---

## Module 4 — Admin Features

**Goal:** Operate it like a DBaaS SME.

- **Compute/autoscaling:** `update-endpoint` to change min/max CU. Rule: **max − min ≤
  8 CU**; range 0.5–112 CU (2 GB RAM/CU). Tune scale-to-zero timeout.
- **Read replicas:** add `ENDPOINT_TYPE_READ_ONLY` endpoints; read-scaling vs the
  retired "readable secondaries" HA model.
- **Branch protection:** `is_protected=true` on production (blocks delete/reset/archive).
- **Unity Catalog integration:**
  - Register the Lakebase DB as a UC catalog → query Postgres tables from Databricks
    SQL/notebooks.
  - **Reverse ETL / synced tables:** Delta → Lakebase for low-latency serving.
    (Current limit: no Postgres→Delta sync yet.)
- **Data API (PostgREST):** enable `authenticator`/`api_user` roles, query tables over
  HTTPS with the OAuth token.
- **Cost model:** $0.111/CU-hr compute, $0.35/GB-mo storage, $0.20/GB-mo PITR — build a
  small sizing example.
- **Roles & security:** Postgres roles vs Databricks identity; OAuth vs native
  passwords; SSL enforcement.
- **Internal admin visibility (`lakebase-admin` MCP tools):** list clusters, operations,
  pageservers, safekeepers, global/regional settings — for understanding the
  Neon-derived internals (pageserver = storage, safekeeper = WAL quorum).

**Milestone:** A one-pager: scaling knobs, replica strategy, UC/reverse-ETL wiring,
cost drivers, admin surfaces.

---

## Suggested Pacing

| Session | Module | Output |
|---|---|---|
| 1 | Module 0 + 1 | Live DB + NYC Taxi/PostGIS dataset + Python app connected |
| 2 | Module 2 | Branch → change → promote workflow |
| 3 | Module 3 | PITR runbook |
| 4 | Module 4 | Admin/ops one-pager |

---

## Known Limitations (avoid dead ends)

- No Databricks Apps UI integration yet (connect manually via credentials)
- No Feature Store integration
- No stateful AI agents (LangChain memory)
- No direct Provisioned → Autoscaling migration (use `pg_dump`/`pg_restore` or reverse ETL)
- No Postgres → Delta sync (only Delta → Postgres reverse ETL)
- Autoscaling range: max − min cannot exceed 8 CU

---

## Tier Reference (Autoscaling vs Provisioned)

| Aspect | Autoscaling (Preferred) | Provisioned (Legacy) |
|---|---|---|
| CLI | `databricks postgres` | `databricks database` |
| SDK module | `w.postgres` | `w.database` |
| Top-level resource | Project | Instance |
| Capacity | 0.5–112 CU, auto (2 GB/CU) | Fixed CU_1/2/4/8 (16 GB/CU) |
| Scale-to-zero | Yes | No |
| Branching | First-class | Via PITR only |
| Operations | Long-running (`.wait()`) | Synchronous |
