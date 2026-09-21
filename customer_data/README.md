# Customer data tables

This module creates a small Unity Catalog data model for synthetic customer,
transaction, engagement, feature, and prediction data. It is intended for the
hackathon sample environment and uses managed Delta tables.

## Data model

| Object | Grain |
|---|---|---|
| `customers` | One current row per customer |
| `products` | One current row per product |
| `transactions` | One row per transaction |
| `transaction_items` | One row per transaction line |
| `customer_events` | One row per customer interaction |
| `customer_features` | One row per customer and snapshot date |
| `customer_predictions` | One row per model scoring event |
| `customer_360` | View of each customer with the latest features and prediction |

Every object is created in `databricks-hackathon.00data`. All tables are managed
Delta tables with liquid clustering and Change Data Feed enabled.

## Create the objects

1. Open [`sql/00_create_customer_data.sql`](sql/00_create_customer_data.sql) in
   the Databricks SQL editor or import it as a SQL notebook.
2. Attach a SQL warehouse.
3. Confirm that the fixed target `databricks-hackathon.00data` is appropriate.
4. Use **Run all** to create the schema and its objects in dependency order.
5. Run [`sql/01_add_check_constraints.sql`](sql/01_add_check_constraints.sql)
   once to add the enforced Delta quality constraints.
6. Run [`sql/10_validate_customer_data.sql`](sql/10_validate_customer_data.sql)
   after loading data.

The principal executing the script needs `USE CATALOG` and `CREATE SCHEMA` on
the selected catalog. Consumers need `USE CATALOG`, `USE SCHEMA`, and `SELECT`
on the resulting objects.

## Design notes

- IDs are strings so UUIDs and source-system identifiers are both supported.
- Money uses fixed-precision decimals; probabilities use doubles constrained to
  the range 0–1.
- Primary-key constraints are informational in Databricks and therefore marked
  `NOT ENFORCED`. The validation script checks uniqueness explicitly.
- Check constraints are added after table creation because this Databricks SQL
  environment does not accept them inline. They are enforced when data is written.
- Foreign keys are documented by column naming and validated with queries rather
  than declared, which keeps ingestion order flexible.
- Generated date columns support date filtering without duplicating application
  logic.
- `CREATE TABLE IF NOT EXISTS` makes initial provisioning rerunnable. It does not
  migrate a table that already exists; make later schema changes with reviewed
  `ALTER TABLE` migration scripts.
- Keep `synthetic_record = true` for hackathon data. Do not load real personal
  data without applying the appropriate governance, masking, and retention rules.

## Load order

Load data in this order to make relationship checks straightforward:

1. `customers` and `products`
2. `transactions`
3. `transaction_items` and `customer_events`
4. `customer_features` and `customer_predictions`

## Generate the validation sample

[`generate_sample_data.py`](generate_sample_data.py) creates the approved,
deterministic sample with seed 42 and merges it into the existing tables:

- 50 customers and 40 products
- 1,000 transactions and 2,500 reconciled line items
- 2,000 customer events
- 50 feature snapshots and 50 predictions

Run it with the authenticated workspace profile:

```bash
DATABRICKS_CONFIG_PROFILE=bloomreach-hackathon-workspace \
uv run --with polars --with numpy --with mimesis --with typing-extensions \
  --with 'databricks-connect>=16.4,<17.0' \
  customer_data/generate_sample_data.py
```

Use `--dry-run` to generate and validate locally without writing to Unity
Catalog. Stable IDs and `MERGE` operations make retries idempotent.

After loading the seed-42 sample, run
[`sql/11_validate_sample_data.sql`](sql/11_validate_sample_data.sql) for exact
row-count, relationship, financial-reconciliation, and temporal checks.
