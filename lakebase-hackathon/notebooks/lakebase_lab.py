# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0

# COMMAND ----------

# MAGIC %md
# MAGIC # Lakebase Hands-On Lab
# MAGIC
# MAGIC A friendly, hands-on tour of **Databricks Lakebase** — fully-managed PostgreSQL that runs
# MAGIC right inside Databricks — using one small **NYC Taxi + PostGIS** dataset.
# MAGIC
# MAGIC By the end you will have:
# MAGIC
# MAGIC 0. Lakebase - a quick word.
# MAGIC 1. Created a database, logged in, built a table, and run queries.
# MAGIC 2. **Branched** the database to test a change safely.
# MAGIC 3. **Recovered** data after an accidental delete (point-in-time recovery).
# MAGIC 4. Learned how to operate it and what it costs.
# MAGIC
# MAGIC > Runs on Databricks serverless. Uses `databricks-sdk>=0.81.0`, `psycopg[binary]>=3.0`,
# MAGIC > and `sqlalchemy>=2.0` (installed in the next cell).

# COMMAND ----------

# MAGIC %md
# MAGIC ## What is Lakebase?
# MAGIC
# MAGIC **Lakebase is a fully-managed PostgreSQL database that runs inside Databricks.** It is
# MAGIC ordinary Postgres — your SQL, tools, and drivers all work — with two design choices that
# MAGIC make it special:
# MAGIC
# MAGIC 1. **Storage and compute are separate.** The *data* is kept in one place; the *engine*
# MAGIC    that runs your queries is a separate thing you can start, stop, and resize. When nobody
# MAGIC    is using the database, that engine can **shrink to nothing ("scale to zero")** so you
# MAGIC    stop paying for it — and it wakes up automatically on the next connection.
# MAGIC 2. **Storage keeps its history.** Think of it like *version history* (an undo log) for your
# MAGIC    whole database. Because every past state is still available, two very useful features
# MAGIC    come almost for free:
# MAGIC    * **Branches** — an instant, cheap *copy* of the database to experiment on, without
# MAGIC      duplicating the data (Module 2).
# MAGIC    * **Point-in-time recovery** — rewind to how the data looked at an earlier moment
# MAGIC      (Module 3).
# MAGIC
# MAGIC **How things are named** (a simple hierarchy, like nested folders):
# MAGIC
# MAGIC ```
# MAGIC Project             e.g. projects/lakebase-lab-…   (the top-level container)
# MAGIC   └── Branch        e.g. .../branches/production   (a version/copy of the data)
# MAGIC        └── Endpoint  e.g. .../endpoints/primary     (the compute that runs queries)
# MAGIC Inside a branch:  Database → Schema → Tables        (normal Postgres objects)
# MAGIC ```
# MAGIC
# MAGIC Creating a project automatically gives you a `production` branch, a primary endpoint, and a
# MAGIC starter database. We add our own `nyc_taxi` database on top.
# MAGIC
# MAGIC 📖 Learn more: [Lakebase overview](https://docs.databricks.com/aws/en/oltp/) ·
# MAGIC [Scale to zero](https://docs.databricks.com/aws/en/oltp/projects/scale-to-zero)

# COMMAND ----------

# MAGIC %md
# MAGIC ### First, install the Postgres tools
# MAGIC
# MAGIC We install the **Databricks SDK** (to create and manage the database), **`psycopg`** +
# MAGIC **`SQLAlchemy`** — two of the most common, completely standard tools for talking to *any*
# MAGIC PostgreSQL database — and **`pyway`**, a Python schema-migration tool we use in Module 2.
# MAGIC That these ordinary tools just work is the first sign that Lakebase is plain Postgres.
# MAGIC (Installing everything here, up front, avoids a mid-notebook restart.)

# COMMAND ----------

# MAGIC %pip install -U "databricks-sdk>=0.81.0" "psycopg[binary]>=3.0" "sqlalchemy>=2.0" "pyway"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 0 — Connect to Databricks and sign in
# MAGIC
# MAGIC This cell loads the libraries and creates a `WorkspaceClient` — your handle to Databricks.
# MAGIC Notice the last line prints **your own email**: in Lakebase, *you* are the database user
# MAGIC (more on that in Module 1). We also derive a per-user project id and define a few names
# MAGIC (`nyc_taxi`, the branches) that we reuse throughout the lab.

# COMMAND ----------

# DBTITLE 1,Imports & configuration
"""Load our tools, connect to Databricks, and remember the names we reuse.

- ``WorkspaceClient`` is our remote control for Lakebase (create projects, branches,
  endpoints, and mint login tokens).
- ``psycopg`` is a standard PostgreSQL driver — the same one you would use anywhere.
- The ``lakebase_conn`` helpers power the token-refresh demo later in Module 1.
"""

import time
from pathlib import Path

import psycopg
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.postgres import (
    Branch,
    BranchSpec,
    Duration,
    Endpoint,
    EndpointSpec,
    EndpointType,
    Project,
    ProjectSpec,
)

# The connection manager lives in a sibling module so it is unit-testable offline.
from lakebase_conn import (
    LakebaseTokenProvider,
    build_engine,
    derive_project_id,
    needs_refresh,
    workspace_credential_fn,
)

w = WorkspaceClient()  # our connection to Databricks
me = w.current_user.me()
USER = me.user_name  # your email — this is also your Postgres username

# Names we reuse everywhere. Resource names are hierarchical, like nested folders:
#   projects/<project>/branches/<branch>/endpoints/<endpoint>
#
# The project name must be unique *within the workspace* — this lab is run by many people —
# so we derive it from your identity. Uniqueness is guaranteed by your numeric Databricks
# user id; the email slug is only there so the project is easy to recognize. Everything
# nested inside the project (nyc_taxi, the branches) is per-user isolated, so it stays fixed.
PROJECT_ID = derive_project_id(me.id, USER)
PROJECT = f"projects/{PROJECT_ID}"
PROD_BRANCH = f"{PROJECT}/branches/production"
DATABASE = "nyc_taxi"


def _repo_subdir(name: str) -> Path:
    """Find a repo folder (e.g. ``sql/``) by walking up from the working directory.

    Works whether the notebook's working directory is the repo root or ``notebooks/``.
    """
    here = Path.cwd().resolve()
    for base in (here, *here.parents):
        if (base / name).is_dir():
            return base / name
    raise FileNotFoundError(f"could not locate {name}/ from {here}")


# All SQL is version-controlled under sql/ (single source of truth) — we read it, not inline it.
SQL_DIR = _repo_subdir("sql")

print("Signed in as", USER)
print("Project id:", PROJECT_ID)
print("SQL dir:", SQL_DIR)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 1 — Create a Database & Log In
# MAGIC
# MAGIC ### How logging in works (read this first)
# MAGIC
# MAGIC Lakebase does **not** use a fixed database username/password stored in a config file.
# MAGIC Instead:
# MAGIC
# MAGIC * **Who you are:** your **Databricks identity** (your email) *is* the Postgres username.
# MAGIC * **How you log in:** you ask Databricks for a short-lived **login token** and use it as the
# MAGIC   Postgres *password*. That token is an **OAuth token that expires after 1 hour**, so there
# MAGIC   is no long-lived password to leak. Every connection uses SSL (`sslmode=require`).
# MAGIC * **In code:** `w.postgres.generate_database_credential(endpoint=…)` returns a fresh token,
# MAGIC   and `w.postgres.get_endpoint(…)` gives you the database host to connect to.
# MAGIC
# MAGIC A few limits worth knowing: connections drop after a **24-hour idle timeout** and a **3-day
# MAGIC maximum lifetime**, and the very first connection after the engine has scaled to zero takes
# MAGIC a moment to wake up. For long-running apps that cannot refresh a token every hour, Lakebase
# MAGIC also supports classic **native Postgres passwords** — but tokens are the safer default, and
# MAGIC we will show how to refresh them automatically.
# MAGIC
# MAGIC 📖 Learn more: [Authentication](https://docs.databricks.com/aws/en/oltp/projects/authentication) ·
# MAGIC [Connect to a database](https://docs.databricks.com/aws/en/oltp/projects/connect)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 1 — Create the database project
# MAGIC
# MAGIC We create a Postgres 18 project whose name is unique to you (e.g. `lakebase-lab-…`, derived
# MAGIC in the previous cell). This is **idempotent**: if it already
# MAGIC exists, we just reuse it. A brand-new project provisions real infrastructure, so the first
# MAGIC run takes a couple of minutes; re-runs are instant. Afterwards we look up the **host** and
# MAGIC mint a fresh 1-hour **token** for the primary endpoint.

# COMMAND ----------

# DBTITLE 1,Create the project (idempotent, long-running)
"""Create (or reuse) the Lakebase project, then find its host + a login token.

``create_project(...).wait()`` provisions storage + compute and blocks until it is ready.
This is idempotent — re-running reuses an existing project.

Note on existence checks: ``delete_project`` is a *soft* delete, and ``get_project`` still
resolves a soft-deleted project (as a ghost with no state) during its retention window — so
it is NOT a reliable "does it exist?" test. We check membership in ``list_projects`` instead,
which soft-deleted projects drop out of. (If you tore this lab down earlier and hit
"A soft-deleted project currently has this resource name", purge the tombstone once:
``databricks api delete "/api/2.0/postgres/projects/<PROJECT_ID>?purge=true" -p <profile>``,
then re-run this cell.)
"""


def project_is_active(name: str) -> bool:
    """True only if the project is live (present in list_projects, not soft-deleted)."""
    return any(p.name == name for p in w.postgres.list_projects())


if project_is_active(PROJECT):
    print("Project already exists:", PROJECT)
else:
    # The display name is set to PROJECT_ID so the UI shows *your* per-user project
    # (e.g. "lakebase-lab-<you>-<id>"), not a generic "Lakebase Lab" shared by everyone.
    w.postgres.create_project(
        project=Project(spec=ProjectSpec(display_name=PROJECT_ID, pg_version=18)),
        project_id=PROJECT_ID,
    ).wait()  # blocks until the project is ready
    print("Created project:", PROJECT)


def primary_endpoint_name(branch: str) -> str:
    """Discover the primary endpoint on a branch (auto-created id is not guaranteed)."""
    endpoints = list(w.postgres.list_endpoints(parent=branch))
    if not endpoints:
        raise RuntimeError(f"no endpoints on {branch}")
    return endpoints[0].name


def connection_bits(endpoint_name: str):
    """Return (host, token) for an endpoint, generating a fresh 1-hour token."""
    host = w.postgres.get_endpoint(name=endpoint_name).status.hosts.host
    token = w.postgres.generate_database_credential(endpoint=endpoint_name).token
    return host, token


EP_PROD = primary_endpoint_name(PROD_BRANCH)  # the compute on production
HOST, TOKEN = connection_bits(EP_PROD)  # where to connect + how to log in
print("Endpoint:", EP_PROD)
print("Host:", HOST)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 2 — Build the NYC Taxi dataset (with PostGIS)
# MAGIC
# MAGIC Now we prove it is real Postgres. We create a `nyc_taxi` database, turn on the stock
# MAGIC **PostGIS** geospatial extension with a plain `CREATE EXTENSION`, and build a small 5-table
# MAGIC star schema: a `trips` fact table plus `vendors`, `rate_codes`, `payment_types`, and a
# MAGIC spatial `taxi_zones` table — with real **foreign keys** and **GIST** spatial indexes. Then
# MAGIC we seed a few rows. Watch for the PostGIS version and `trips seeded: 3`.
# MAGIC
# MAGIC **A tidy home for our tables:** rather than dump everything into the default `public`
# MAGIC schema, `01_schema.sql` creates a dedicated **`cabs`** schema and makes it the default via
# MAGIC `ALTER DATABASE nyc_taxi SET search_path = cabs, public`. That one line means every later
# MAGIC connection — these notebook cells, `psql`, `pyway`, and any branch we clone — resolves a
# MAGIC bare `trips` to `cabs.trips` automatically, while PostGIS stays shared in `public`. So the
# MAGIC queries below stay clean (`FROM trips`) even though the table really lives in `cabs`.
# MAGIC
# MAGIC 📖 Learn more: [Postgres extensions](https://docs.databricks.com/aws/en/oltp/projects/extensions)

# COMMAND ----------

# DBTITLE 1,Initialize the nyc_taxi dataset (PostGIS + 5-table star schema)
"""Create the nyc_taxi database, then build + seed it from the checked-in bootstrap SQL.

Two connections are used: first to the default ``postgres`` database just to run
CREATE DATABASE (the default DB's public schema is restricted), then to ``nyc_taxi`` to
apply ``sql/bootstrap/01_schema.sql`` and ``sql/bootstrap/02_seed.sql``. The SQL lives in
files under ``sql/`` (single source of truth) — we read it here rather than inline it.

``01_schema.sql`` creates a ``cabs`` schema and sets ``search_path = cabs, public`` at the
database level, so every connection (including the seed run and every branch later) sees
``trips`` as ``cabs.trips`` without us having to qualify it.
"""
# Create the database (default DB's public schema is restricted).
with psycopg.connect(
    f"host={HOST} dbname=postgres user={USER} password={TOKEN} sslmode=require",
    autocommit=True,
) as conn, conn.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'nyc_taxi'")
    if cur.fetchone() is None:
        cur.execute("CREATE DATABASE nyc_taxi")
        print("Created database nyc_taxi")
    else:
        print("Database nyc_taxi already exists")

# Read the bootstrap SQL from files (schema first, then seed).
schema_sql = (SQL_DIR / "bootstrap" / "01_schema.sql").read_text()
seed_sql = (SQL_DIR / "bootstrap" / "02_seed.sql").read_text()

with psycopg.connect(
    f"host={HOST} dbname={DATABASE} user={USER} password={TOKEN} sslmode=require"
) as conn:
    with conn.cursor() as cur:
        cur.execute(schema_sql)  # extension, tables, foreign keys, GIST indexes
        cur.execute(seed_sql)  # a few dimension rows, zones, and sample trips
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT postgis_full_version()"
        )  # proof the stock extension is live
        print(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM trips")
        print("trips seeded:", cur.fetchone()[0])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 3a — Read the data (a join + two geospatial reads)
# MAGIC
# MAGIC First, just **look** at the freshly-seeded data — no changes yet. We run a `SELECT` join
# MAGIC across the star schema and two **geospatial** reads: `ST_DistanceSphere` gives the
# MAGIC straight-line distance between pickup and dropoff, and `ST_Contains` asks which zone
# MAGIC polygon a pickup point falls inside — full GIS, right inside your operational database.
# MAGIC
# MAGIC At this point `trips` has **all 3 seeded rows** (including the voided trip). Keep that in
# MAGIC mind — Step 3b changes it.

# COMMAND ----------

# DBTITLE 1,Read only — the join + two PostGIS spatial reads
"""
Read ``trips`` (a star-schema join + two PostGIS spatial reads)
"""
# The reusable read query — we run the identical statement again in Step 3b to show the delta.
TRIPS_JOIN = """
    SELECT t.trip_id, v.name, pz.zone AS pickup_zone, dz.zone AS dropoff_zone,
           pt.description AS payment, t.total_amount,
           ROUND(ST_DistanceSphere(t.pickup_point, t.dropoff_point)::numeric, 0) AS meters
    FROM trips t
    JOIN vendors v        ON v.vendor_id     = t.vendor_id
    JOIN taxi_zones pz    ON pz.location_id  = t.pickup_location_id
    JOIN taxi_zones dz    ON dz.location_id  = t.dropoff_location_id
    JOIN payment_types pt ON pt.payment_type = t.payment_type
    ORDER BY t.pickup_datetime
"""
from tabulate import tabulate
with psycopg.connect(
    f"host={HOST} dbname={DATABASE} user={USER} password={TOKEN} sslmode=require"
) as conn, conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM trips")
    print(f"Trips:{cur.fetchone()[0]} \n" )

    # READ (join + straight-line distance in meters)
    cur.execute(TRIPS_JOIN)
    headers = [desc[0] for desc in cur.description]
    data = cur.fetchall()
    print(tabulate(data, headers=headers, tablefmt="pipe", numalign="left", stralign="left"))
    print("\n Zones:\n")
    # READ (spatial predicate): which zone contains each pickup point?
    cur.execute(
        "SELECT t.trip_id as trip_id, z.zone as zone FROM trips t "
        "JOIN taxi_zones z ON ST_Contains(z.geom, t.pickup_point)"
    )
    pheaders = [desc[0] for desc in cur.description]
    pdata = cur.fetchall()
    print(tabulate(pdata, headers=pheaders, tablefmt="pipe", numalign="left", stralign="left"))
    # print("\npoint-in-zone:", cur.fetchall())

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 3b — Change the data (UPDATE + DELETE), then look again
# MAGIC
# MAGIC Now the **writes**, kept separate so the reads above stay clean. We correct one fare with
# MAGIC an `UPDATE`, then `DELETE` the single voided trip (`payment_type = 6`). Straight after, we
# MAGIC re-run the *same* join from Step 3a so you can see the **before → after** in one place.
# MAGIC
# MAGIC > **Why the SQL editor can look different:** this cell mutates the data. Once it has run,
# MAGIC > `trips` has **2 rows** and trip 1's total is updated — so a query you run in the SQL
# MAGIC > editor afterwards matches the *after* output here, not the 3-row *before* from Step 3a.
# MAGIC > Re-running Step 3a now will also show 2 rows. That is the data changing, not a bug.

# COMMAND ----------

# DBTITLE 1,Write — UPDATE + DELETE, then re-read to show the delta
"""Apply an UPDATE and a DELETE to ``trips``, then re-run the Step 3a join to show the delta.

The DELETE removes the one voided trip (payment_type 6), so the row count drops from 3 to 2
for the rest of the lab. Printing the count and the join before *and* after makes the change
explicit — and reconciles the notebook with what you would see in the SQL editor.
"""
with psycopg.connect(
    f"host={HOST} dbname={DATABASE} user={USER} password={TOKEN} sslmode=require"
) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM trips")
        print("before:", cur.fetchone()[0], "rows")

        # UPDATE — correct trip 1's fare (and recompute its total).
        cur.execute(
            "UPDATE trips SET fare_amount = 72.50, "
            "total_amount = 72.50 + tip_amount + 4.80 WHERE trip_id = 1"
        )
        # DELETE — remove the voided trip (payment_type 6).
        cur.execute("DELETE FROM trips WHERE payment_type = 6")
    conn.commit()

    # Re-read with the SAME query as Step 3a to show the after-state.
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM trips")
        print("after: ", cur.fetchone()[0], "rows (voided trip deleted)\n")
        cur.execute(TRIPS_JOIN)
        columns = [desc[0] for desc in cur.description]
        table = cur.fetchall()
        print(tabulate(table, headers=columns, tablefmt="pipe", numalign="left", stralign="left"))
        # print("trip_id | vendor | pickup -> dropoff | payment | total | meters")
        # for row in cur.fetchall():
        #     print(row)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 4 — Keep a long-lived connection healthy (auto-refresh the token)
# MAGIC
# MAGIC A real app keeps a pool of connections open for days, but our login token expires every
# MAGIC hour. This cell builds a standard **SQLAlchemy** engine with a small listener that runs
# MAGIC just before each new connection: if the token is older than ~50 minutes, it quietly mints
# MAGIC a fresh one. Your query code does not change — the refresh is invisible.
# MAGIC
# MAGIC **How it works — three small pieces (all in `notebooks/lakebase_conn.py`):**
# MAGIC
# MAGIC 1. **`needs_refresh(issued_at, now)` — the rule.** A pure function (no I/O) that returns
# MAGIC    `True` once a token is ≥ 50 minutes old (`REFRESH_AFTER_SECONDS = 3000`). We refresh at
# MAGIC    50, not 60, minutes to leave headroom. Being pure, it is trivially unit-tested offline.
# MAGIC 2. **`LakebaseTokenProvider` — the cache.** Holds the current token and the time it was
# MAGIC    issued. `get_token()` returns the cached token, but if it is missing or `needs_refresh`
# MAGIC    says it is stale, it first calls a `credential_fn` to mint a new one. Here that
# MAGIC    `credential_fn` is `workspace_credential_fn(w)`, which wraps
# MAGIC    `w.postgres.generate_database_credential(...)`.
# MAGIC 3. **`build_engine(...)` — the wiring.** Creates a normal SQLAlchemy engine, then registers
# MAGIC    a listener on SQLAlchemy's **`do_connect`** event. `do_connect` fires *just before* every
# MAGIC    new physical connection opens; our listener sets `cparams["password"] =
# MAGIC    token_provider.get_token()`. So the freshest valid token is injected as the password on
# MAGIC    each connect — the pool never opens a connection with an expired credential.
# MAGIC
# MAGIC The payoff: your query code is ordinary SQLAlchemy (`engine.connect()`, `execute(text(...))`).
# MAGIC The credential lifecycle is handled once, in the engine, and stays out of your way.
# MAGIC
# MAGIC > *Note: this is **app-side** pooling with token refresh. Lakebase also has a Neon-style
# MAGIC > **server-side PgBouncer pooler** (`-pooler` host, up to 10k clients) — but it needs a
# MAGIC > native password role, not OAuth, so it's a separate path from this secure token flow.*

# COMMAND ----------

# DBTITLE 1,Resilient engine — token auto-refresh via do_connect
"""Build a SQLAlchemy engine that refreshes the 1-hour token automatically.

``needs_refresh`` is the pure 50-minute rule (unit-tested offline); the provider mints a
new token when the old one is stale; the engine's ``do_connect`` listener injects it before
every physical connection. This is the pattern a production app would use.
"""
# Piece 1 — the rule. Sanity-check it inline: stale at 3000s (50 min), fresh at 2999s.
assert needs_refresh(0, 3000) and not needs_refresh(0, 2999)

# Piece 2 — the cache. The provider mints a token via generate_database_credential and
# hands back the cached one until needs_refresh() flips at the 50-minute mark.
token_provider = LakebaseTokenProvider(EP_PROD, workspace_credential_fn(w))

# Piece 3 — the wiring. build_engine registers a do_connect listener that calls
# token_provider.get_token() and injects it as the password before every physical connect.
engine = build_engine(HOST, DATABASE, USER, token_provider)

from sqlalchemy import text

# From here on it is ordinary SQLAlchemy — the token refresh happens under the hood.
with engine.connect() as conn:
    print(
        "trips via SQLAlchemy pool:",
        conn.execute(text("SELECT count(*) FROM trips")).scalar(),
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 2 — Branch the Database to Test a Change Safely
# MAGIC
# MAGIC A **branch** is an instant, near-free copy of the whole database. Because it shares the
# MAGIC original's storage until you change something (copy-on-write), you can fork production,
# MAGIC experiment freely, and throw the branch away — without touching or duplicating the real
# MAGIC data.
# MAGIC
# MAGIC We branch production, add a new column **only on the branch**, confirm production is
# MAGIC untouched, then "promote" the change. **One honest caveat:** there is *no* Git-style
# MAGIC automatic merge back into production. You promote the **migration** — you re-apply the same,
# MAGIC now-validated change to production (ideally through your normal migration tool).
# MAGIC
# MAGIC 📖 Learn more: [Branches](https://docs.databricks.com/aws/en/oltp/projects/branches)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 1 — Fork `production` into `feature-x` and give it compute
# MAGIC
# MAGIC We fork `production` into a branch called `feature-x` (with a 7-day auto-expiry) and attach
# MAGIC a small read-write endpoint to it. The `nyc_taxi` data is already there for free via
# MAGIC copy-on-write — no data is copied until we change something. Nothing is modified yet; this
# MAGIC cell only creates the branch and its compute.

# COMMAND ----------

# DBTITLE 1,Create the feature-x branch + its own endpoint
"""Fork production -> feature-x and attach a read-write endpoint (no data change yet).

Idempotent guards (get_branch / get_endpoint) make re-runs safe. We finish by minting a
token for the branch's OWN endpoint into ``f_host`` / ``f_token`` — the next cell reuses
these so its writes land on the branch, never on production.
"""
FEATURE = "feature-x"
FBRANCH = f"{PROJECT}/branches/{FEATURE}"

try:
    w.postgres.get_branch(name=FBRANCH)
    print("Branch exists:", FBRANCH)
except Exception:
    w.postgres.create_branch(
        parent=PROJECT,
        branch=Branch(
            spec=BranchSpec(source_branch=PROD_BRANCH, ttl=Duration(seconds=604800))
        ),
        branch_id=FEATURE,
    ).wait()
    print("Created branch:", FBRANCH)

FEP = f"{FBRANCH}/endpoints/primary"
try:
    w.postgres.get_endpoint(name=FEP)
    print("Endpoint exists:", FEP)
except Exception:
    w.postgres.create_endpoint(
        parent=FBRANCH,
        endpoint=Endpoint(
            spec=EndpointSpec(
                endpoint_type=EndpointType.ENDPOINT_TYPE_READ_WRITE,
                autoscaling_limit_min_cu=0.5,
                autoscaling_limit_max_cu=2.0,
            )
        ),
        endpoint_id="primary",
    ).wait()
    print("Created endpoint:", FEP)

# Connect to the branch's OWN compute (its own host + a fresh token).
f_host, f_token = connection_bits(FEP)
print("Branch endpoint ready — host:", f_host)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 2 — Make an isolated change on the branch
# MAGIC
# MAGIC Now we add and backfill a `congestion_surcharge` column — **on `feature-x` only**. Because
# MAGIC we connect through the branch's own endpoint (`f_host` / `f_token` from Step 1), these
# MAGIC writes cannot touch `production`. This is the "experiment freely" moment.

# COMMAND ----------

# DBTITLE 1,Apply the isolated migration (ALTER + backfill) on feature-x
"""Apply the schema change to feature-x only: add + backfill congestion_surcharge.

These statements run against the branch's own endpoint (``f_host`` / ``f_token``), so they
are fully isolated from production — which we prove in the next section.
"""
with psycopg.connect(
    f"host={f_host} dbname={DATABASE} user={USER} password={f_token} sslmode=require"
) as conn:
    with conn.cursor() as cur:
        # Add the new column (idempotent).
        cur.execute(
            "ALTER TABLE trips ADD COLUMN IF NOT EXISTS "
            "congestion_surcharge NUMERIC(8,2) DEFAULT 0"
        )
        # Backfill $2.50 for Manhattan pickups.
        cur.execute(
            "UPDATE trips t SET congestion_surcharge = 2.50 "
            "FROM taxi_zones z WHERE z.location_id = t.pickup_location_id "
            "AND z.borough = 'Manhattan'"
        )
    conn.commit()
print("Applied congestion_surcharge on feature-x (branch only).")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 3 — See the change on the branch
# MAGIC
# MAGIC Read `feature-x` back to confirm the new column exists and the Manhattan backfill worked.
# MAGIC (In the next section we run the *same* read against `production` — where the column is
# MAGIC absent — to prove the two branches are truly independent.)

# COMMAND ----------

# DBTITLE 1,Query feature-x — the new column is present
"""Read the new column back from feature-x to confirm the isolated change took effect."""
with psycopg.connect(
    f"host={f_host} dbname={DATABASE} user={USER} password={f_token} sslmode=require"
) as conn, conn.cursor() as cur:
    cur.execute(
        "SELECT trip_id, total_amount, congestion_surcharge FROM trips ORDER BY trip_id"
    )
    print("feature-x trips (trip_id, total_amount, congestion_surcharge):")
    data = cur.fetchall()
    columns = [ desc[0] for desc in cur.description]  
    print(tabulate(data, headers=columns, tablefmt="pipe", numalign="left", stralign="left")) 

# COMMAND ----------

# MAGIC %md
# MAGIC ### Verify the change is isolated (production is untouched)
# MAGIC
# MAGIC First, proof the branch is truly separate: we run the same `SELECT congestion_surcharge`
# MAGIC against **production**, and it should **fail** — the column does not exist there. That
# MAGIC error *is* the point: the change we made on `feature-x` never leaked into production.

# COMMAND ----------

# DBTITLE 1,Verify isolation — the column is absent on production
"""Confirm feature-x's column is absent on production. The SELECT is EXPECTED to fail.

We connect to the production endpoint and mint a token into ``p_host`` / ``p_token`` — the
promotion cell below reuses them. The failed SELECT (caught here) is the proof of isolation.
"""
p_host, p_token = connection_bits(EP_PROD)
with psycopg.connect(
    f"host={p_host} dbname={DATABASE} user={USER} password={p_token} sslmode=require"
) as conn, conn.cursor() as cur:
    try:
        cur.execute("SELECT congestion_surcharge FROM trips LIMIT 1")
        print("WARNING: column present on production — not isolated!")
    except Exception:
        conn.rollback()
        print(
            "Confirmed: congestion_surcharge is absent on production (isolated to feature-x)"
        )

# COMMAND ----------

# MAGIC %md
# MAGIC ### Promote the change to production
# MAGIC
# MAGIC Now we "promote" the validated change by re-running the same migration against
# MAGIC `production`. **Remember: there is no merge button** — promoting *is* re-applying the
# MAGIC change you validated on the branch. We read the column back afterwards to confirm it is
# MAGIC now present on production too. (The next section shows the repeatable way to do this with
# MAGIC a migration tool instead of a hand-run `ALTER`.)

# COMMAND ----------

# DBTITLE 1,Promote — re-apply the same migration to production
"""Promote by re-applying the exact ALTER + backfill to production, then read it back.

Reuses ``p_host`` / ``p_token`` from the isolation check. There is no git-style branch
merge in Lakebase; you promote the migration, not the branch.
"""
with psycopg.connect(
    f"host={p_host} dbname={DATABASE} user={USER} password={p_token} sslmode=require"
) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE trips ADD COLUMN IF NOT EXISTS "
            "congestion_surcharge NUMERIC(8,2) DEFAULT 0"
        )
        cur.execute(
            "UPDATE trips t SET congestion_surcharge = 2.50 "
            "FROM taxi_zones z WHERE z.location_id = t.pickup_location_id "
            "AND z.borough = 'Manhattan'"
        )
    conn.commit()
    # Confirm the column is now present on production.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trip_id, total_amount, congestion_surcharge FROM trips ORDER BY trip_id"
        )
        print("Promoted. production trips now carry congestion_surcharge:")
        data = cur.fetchall()
        columns = [ desc[0] for desc in cur.description]  
        print(tabulate(data, headers=columns, tablefmt="pipe", numalign="left", stralign="left")) 

# COMMAND ----------

# MAGIC %md
# MAGIC ### A repeatable promotion: versioned migrations with pyway
# MAGIC
# MAGIC Re-running an `ALTER TABLE` by hand (what we just did) is fine for a demo, but real teams
# MAGIC promote schema changes with a **migration tool** so every environment gets the *same*
# MAGIC change, in order, exactly once, with an audit trail.
# MAGIC [**pyway**](https://github.com/jasondcamp/pyway) is a Python port of Flyway — installable
# MAGIC with `pip` (no JVM needed), so it runs right here in the notebook.
# MAGIC
# MAGIC How it works: you write numbered SQL files — `V01_01__add_congestion_surcharge.sql`,
# MAGIC `V01_02__backfill_manhattan_surcharge.sql`, … — and run `pyway migrate`. pyway keeps a
# MAGIC history table (`public.pyway`), and applies only the versions not yet applied, **in
# MAGIC order**. To "promote" the branch change to production you point pyway at the production
# MAGIC branch with the *same* files you validated on `feature-x` — a repeatable, reviewable,
# MAGIC CI-friendly step that replaces the manual re-`ALTER`.
# MAGIC
# MAGIC The next cell uses the real pyway migration files checked in under `sql/migrations/`, points
# MAGIC `PYWAY_*` environment variables at the production branch (over SSL, using a fresh 1-hour
# MAGIC token), then runs `pyway info` and `pyway migrate`.
# MAGIC
# MAGIC 📖 Learn more: [pyway on GitHub](https://github.com/jasondcamp/pyway)

# COMMAND ----------

# DBTITLE 1,Promote with pyway (versioned migrations, in Python)
"""Demonstrate pyway: promote the schema change as ordered, repeatable migration files.

pyway (a Python port of Flyway) applies numbered ``V*.sql`` files in order, exactly once,
tracking them in a history table — the production-grade alternative to re-running ALTER by
hand. The migration files are version-controlled under ``sql/migrations/``; we point pyway
at that folder and at the *production* branch to promote the same change validated on
feature-x. pyway is a CLI, so we set ``PYWAY_*`` env vars and invoke it via subprocess.
"""
import os
import subprocess

# 1. The versioned migration files are checked in under sql/migrations/ (not written here).
mig_dir = str(SQL_DIR / "migrations")
print("Using migrations from:", mig_dir)

# 2. Point pyway at the PRODUCTION branch (a fresh 1-hour token as the password).
prod_host, prod_token = connection_bits(EP_PROD)
pyway_env = {
    **os.environ,
    "PYWAY_TYPE": "postgres",
    "PYWAY_DATABASE_HOST": prod_host,
    "PYWAY_DATABASE_PORT": "5432",
    "PYWAY_DATABASE_USERNAME": USER,
    "PYWAY_DATABASE_PASSWORD": prod_token,
    "PYWAY_DATABASE_NAME": DATABASE,
    "PYWAY_DATABASE_MIGRATION_DIR": mig_dir,
    "PYWAY_TABLE": "public.pyway",
}

# 3. `pyway info` shows applied vs pending; `pyway migrate` applies the pending ones in order.
for cmd in (["pyway", "info"], ["pyway", "migrate"]):
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, env=pyway_env, capture_output=True, text=True)
    print(result.stdout or result.stderr)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 3 — Recover Data After a Mistake (Point-in-Time Recovery)
# MAGIC
# MAGIC Because storage keeps its history, "recovery" is just **branching from the past**. You pick
# MAGIC a moment in time and create a branch as of that instant — the data as it was then is
# MAGIC already available, so there is no backup to restore and no logs to replay.
# MAGIC
# MAGIC We record a timestamp, delete every row from `trips` (oops), bring the data back by
# MAGIC branching from just before the delete, and finally **promote it back to production** by
# MAGIC re-applying the recovered rows (the same "re-apply, don't merge" idea as Module 2).
# MAGIC
# MAGIC 📖 Learn more: [Instant restore / point-in-time recovery](https://docs.databricks.com/aws/en/oltp/projects/point-in-time-restore)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 1 — Capture T0, then simulate the data loss
# MAGIC
# MAGIC `T0` is our safe moment — the instant we will rewind to. We record it, wait a few seconds
# MAGIC so it clearly precedes the accident, then run a `DELETE FROM trips` on **production**.
# MAGIC To make the disaster real, we immediately count the rows on production: it should be **0**.
# MAGIC The data is gone.

# COMMAND ----------

# DBTITLE 1,Capture T0, then DELETE every trip on production (the "accident")
"""Record the recovery point T0, delete all trips on production, and show the loss (0 rows).

We re-mint a production token here so this section stands on its own. ``T0`` is captured
*before* the delete; the 8-second wait guarantees it strictly precedes the accident.
"""
from datetime import datetime, timezone

from databricks.sdk.service.postgres import Timestamp

p_host, p_token = connection_bits(EP_PROD)  # fresh production connection

T0 = datetime.now(timezone.utc)  # timezone-aware; the moment we will rewind to
print("T0 =", T0.isoformat())
time.sleep(8)  # ensure T0 strictly precedes the deletion

with psycopg.connect(
    f"host={p_host} dbname={DATABASE} user={USER} password={p_token} sslmode=require"
) as conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM trips")  # simulated data loss
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM trips")
        print("Production trips after the delete:", cur.fetchone()[0], "(data is gone)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 2 — Recover by branching from T0
# MAGIC
# MAGIC Here is the whole trick: in Lakebase, **recovery is just branching from the past**. We
# MAGIC create `recovery-branch` from `production` **as of `T0`** (`source_branch_time`) and give
# MAGIC it an endpoint. No backup file to restore, no logs to replay — the storage already keeps
# MAGIC the history, so the data as it looked at `T0` is available instantly.

# COMMAND ----------

# DBTITLE 1,Create recovery-branch from production as of T0
"""Create a point-in-time branch of production as of T0, and attach an endpoint.

``source_branch_time`` is what makes this a point-in-time copy; ``ttl`` is required on any
branch. Idempotent guards keep re-runs safe.
"""
RECOVERY = "recovery-branch"
RBRANCH = f"{PROJECT}/branches/{RECOVERY}"
try:
    w.postgres.get_branch(name=RBRANCH)
    print("Recovery branch exists:", RBRANCH)
except Exception:
    w.postgres.create_branch(
        parent=PROJECT,
        branch=Branch(
            spec=BranchSpec(
                source_branch=PROD_BRANCH,
                # .timestamp() on an aware datetime yields the correct UTC epoch seconds
                source_branch_time=Timestamp(seconds=int(T0.timestamp())),
                ttl=Duration(seconds=86400),  # branch creation requires an expiration
            )
        ),
        branch_id=RECOVERY,
    ).wait()
    print("Created recovery branch from T0")

REP = f"{RBRANCH}/endpoints/primary"
try:
    w.postgres.get_endpoint(name=REP)
    print("Recovery endpoint exists:", REP)
except Exception:
    w.postgres.create_endpoint(
        parent=RBRANCH,
        endpoint=Endpoint(
            spec=EndpointSpec(
                endpoint_type=EndpointType.ENDPOINT_TYPE_READ_WRITE,
                autoscaling_limit_min_cu=0.5,
                autoscaling_limit_max_cu=2.0,
            )
        ),
        endpoint_id="primary",
    ).wait()
    print("Created recovery endpoint")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 3 — Confirm the data is back on the recovery branch
# MAGIC
# MAGIC Connect to the recovery branch and count the trips: they are **back**, exactly as they were
# MAGIC at `T0`. Note that production is still empty — recovery does not undo the delete in place;
# MAGIC it gives you a clean branch with the good data. In **Step 4** we put that data back on
# MAGIC production, the same "re-apply, don't merge" way we promoted the migration in Module 2.

# COMMAND ----------

# DBTITLE 1,Query the recovery branch — the trips are back
"""Read the recovered data from the recovery branch (rows are back), and contrast production.

Connecting to the recovery endpoint shows the data as of T0; a quick re-check of production
shows it is still empty — the recovery branch is where the good data now lives.
"""
r_host, r_token = connection_bits(REP)
with psycopg.connect(
    f"host={r_host} dbname={DATABASE} user={USER} password={r_token} sslmode=require"
) as conn, conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM trips")
    print("recovery-branch trips at T0:", cur.fetchone()[0], "(recovered!)")

with psycopg.connect(
    f"host={p_host} dbname={DATABASE} user={USER} password={p_token} sslmode=require"
) as conn, conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM trips")
    print("production trips (still):", cur.fetchone()[0])

# COMMAND ----------

# MAGIC %md
# MAGIC ### Step 4 — Promote the recovery back to production
# MAGIC
# MAGIC The recovery branch has the good data, but production is still empty. Just like Module 2,
# MAGIC there is no "merge" button — we promote by **re-applying**. Here that is simple: read the
# MAGIC rows from `recovery-branch` and insert them back into `production`. Afterwards production
# MAGIC has its data back and the incident is resolved.
# MAGIC
# MAGIC > In real life you might instead point your app at the recovery branch, or use the
# MAGIC > Databricks console to rewind production to the recovery point. Copying the rows back from
# MAGIC > code, as we do here, is the same idea as re-applying a migration — and needs no merge.

# COMMAND ----------

# DBTITLE 1,Promote — copy the recovered rows from the branch back into production
"""Put the data back on production by copying the recovered rows from the recovery branch.

The recovery branch holds the good data; production is still empty. There is no branch
"merge" (same as promoting the migration in Module 2), so we just read the rows from the
recovery branch and insert them back into production.
"""
# 1. Read every recovered row from the recovery branch.
with psycopg.connect(
    f"host={r_host} dbname={DATABASE} user={USER} password={r_token} sslmode=require"
) as conn, conn.cursor() as cur:
    cur.execute("SELECT * FROM trips ORDER BY trip_id")
    columns = [col.name for col in cur.description]  # column names, in order
    recovered_rows = cur.fetchall()
print("Read", len(recovered_rows), "recovered rows from the recovery branch")

# 2. Insert those rows back into production. (Listing the columns explicitly keeps the
#    read and the write lined up; PostGIS geometry values come back as text and go straight
#    back into their columns, so there is nothing special to do for them.)
column_list = ", ".join(columns)
placeholders = ", ".join(["%s"] * len(columns))
with psycopg.connect(
    f"host={p_host} dbname={DATABASE} user={USER} password={p_token} sslmode=require"
) as conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM trips")  # start from the empty table (safe to re-run)
        cur.executemany(
            f"INSERT INTO trips ({column_list}) VALUES ({placeholders})", recovered_rows
        )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM trips")
        print("production trips after promote-back:", cur.fetchone()[0], "(restored!)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 4 — Operating & Paying for Lakebase
# MAGIC
# MAGIC A quick tour of the knobs you will use in production:
# MAGIC
# MAGIC * **Elastic compute:** the engine scales between a **min and max size** you set, and drops
# MAGIC   **to zero when idle** so you do not pay for an unused database. `update_endpoint` changes
# MAGIC   those limits (size is measured in CU — about 2 GB RAM each; range 0.5–112 CU, and
# MAGIC   max − min ≤ 8 CU). Tune how quickly it sleeps with `suspend_timeout_duration`.
# MAGIC * **Read replicas:** add read-only endpoints (`ENDPOINT_TYPE_READ_ONLY`) to scale out reads.
# MAGIC * **Branch protection:** set `is_protected=True` on `production` to block accidental
# MAGIC   deletes/resets.
# MAGIC * **Unity Catalog:** register the database as a UC foreign catalog to query it from
# MAGIC   Databricks SQL, and sync lakehouse (Delta) tables into Lakebase for low-latency serving.
# MAGIC * **Data API (PostgREST):** query tables over HTTPS using the same OAuth token.
# MAGIC * **What it costs:** roughly **$0.111 / CU-hour** of compute (→ near zero when idle),
# MAGIC   **$0.35 / GB-month** of storage, and **$0.20 / GB-month** for point-in-time history.
# MAGIC * **Security recap:** your Databricks identity + a 1-hour token by default (native Postgres
# MAGIC   passwords are available for tools that need them); SSL is always required.
# MAGIC
# MAGIC 📖 Learn more:
# MAGIC [Compute scaling](https://docs.databricks.com/aws/en/oltp/projects/autoscaling) ·
# MAGIC [Scale to zero](https://docs.databricks.com/aws/en/oltp/projects/scale-to-zero) ·
# MAGIC [Read replicas](https://docs.databricks.com/aws/en/oltp/projects/read-replicas)
# MAGIC
# MAGIC **Cleanup:** when you are done, run **Module 5** below to delete every branch and the
# MAGIC project itself — that frees all compute and storage.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Module 5 — Clean Up (Teardown)
# MAGIC
# MAGIC Lakebase bills for compute (near zero when idle) and for storage, so when you have
# MAGIC finished the lab it is good hygiene to remove everything you created. This module
# MAGIC mirrors `scripts/99_teardown.sh`: it deletes every **non-`production`** branch first
# MAGIC (children before the parent), then deletes the **project**, which cascades to the
# MAGIC production branch, its endpoints, databases, and all data.
# MAGIC
# MAGIC This is **destructive and irreversible** for this project, so the cell below does
# MAGIC nothing until you flip `CONFIRM_TEARDOWN = True`. It is idempotent — already-deleted
# MAGIC resources are skipped, so it is safe to re-run.
# MAGIC
# MAGIC > **Clean wipe with `purge=True`.** By default `delete_project` is a *soft* delete: the
# MAGIC > project lingers in a retention window, and — annoyingly — you cannot recreate a project
# MAGIC > with the same name until the tombstone is gone (`get_project` even still resolves it as
# MAGIC > a ghost). Because this lab always uses the *same* per-user project id, we pass
# MAGIC > **`purge=True`** to delete it **hard**, so the name is immediately reusable and Module 1
# MAGIC > re-provisions cleanly on your next run. (Omit `purge` in real systems where you want the
# MAGIC > retention-window safety net.)
# MAGIC
# MAGIC 📖 Learn more:
# MAGIC [Manage projects](https://docs.databricks.com/aws/en/oltp/projects/manage-projects)

# COMMAND ----------

# DBTITLE 1,Delete every branch and the project (frees all compute + storage)
"""Tear down everything this lab created, with a HARD purge so the name is reusable.

Purges each non-``production`` branch, then the project itself (which cascades to the
production branch, endpoints, databases, and data). ``purge=True`` makes these hard
deletes — no soft-delete tombstone — so re-running the lab reuses the same project id
cleanly. Guarded by ``CONFIRM_TEARDOWN`` and idempotent (list-based skip), mirroring
``scripts/99_teardown.sh``.
"""
CONFIRM_TEARDOWN = True  # flip to True to actually delete this lab's project

if not CONFIRM_TEARDOWN:
    print(
        "Teardown skipped — set CONFIRM_TEARDOWN = True in this cell to delete", PROJECT
    )
else:
    # 1. Purge every non-production branch first (children before the parent project).
    for b in w.postgres.list_branches(parent=PROJECT):
        if b.name.endswith("/branches/production"):
            continue
        print("Purging branch", b.name.rsplit("/branches/", 1)[-1])
        w.postgres.delete_branch(name=b.name, purge=True).wait()

    # 2. Purge the project — hard delete, cascades to everything; name is reusable at once.
    print("Purging project", PROJECT)
    w.postgres.delete_project(name=PROJECT, purge=True).wait()
    print("Teardown complete — project purged (hard delete; the name is reusable now).")