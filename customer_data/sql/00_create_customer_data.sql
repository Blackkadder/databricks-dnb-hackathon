-- Customer data model for Databricks SQL and Unity Catalog.
-- All objects are intentionally colocated in databricks-hackathon.00data.

-- Schemas --------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS `databricks-hackathon`.`00data`
COMMENT 'Customer, commerce, engagement, feature, and prediction data for the hackathon';

-- One current record per customer --------------------------------------------
CREATE TABLE IF NOT EXISTS `databricks-hackathon`.`00data`.`customers` (
  customer_id       STRING    NOT NULL COMMENT 'Stable customer identifier',
  first_name        STRING             COMMENT 'Synthetic customer first name',
  last_name         STRING             COMMENT 'Synthetic customer last name',
  email             STRING             COMMENT 'Synthetic email address',
  phone             STRING             COMMENT 'Synthetic phone number',
  date_of_birth     DATE               COMMENT 'Synthetic date of birth',
  signup_date       DATE      NOT NULL COMMENT 'Date the customer relationship began',
  segment           STRING             COMMENT 'Business-defined customer segment',
  loyalty_tier      STRING             COMMENT 'Current loyalty program tier',
  city              STRING,
  state_province    STRING,
  postal_code       STRING,
  country_code      STRING             COMMENT 'ISO 3166-1 alpha-2 country code',
  preferred_channel STRING             COMMENT 'Preferred communication or sales channel',
  marketing_opt_in  BOOLEAN   NOT NULL DEFAULT false,
  account_status    STRING    NOT NULL DEFAULT 'active',
  synthetic_record  BOOLEAN   NOT NULL DEFAULT true,
  source_system     STRING    NOT NULL DEFAULT 'synthetic_generator',
  source_updated_at TIMESTAMP,
  ingested_at       TIMESTAMP NOT NULL DEFAULT current_timestamp(),
  CONSTRAINT customers_pk PRIMARY KEY (customer_id) NOT ENFORCED
)
USING DELTA
CLUSTER BY (customer_id)
COMMENT 'Conformed current-state synthetic customer profiles'
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.feature.allowColumnDefaults' = 'supported',
  'data_classification' = 'synthetic_customer_data'
);

-- Product reference data -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `databricks-hackathon`.`00data`.`products` (
  product_id    STRING        NOT NULL COMMENT 'Stable product identifier',
  product_name  STRING        NOT NULL,
  category      STRING        NOT NULL,
  subcategory   STRING,
  brand         STRING,
  unit_cost     DECIMAL(18,2),
  list_price    DECIMAL(18,2) NOT NULL,
  active_flag   BOOLEAN       NOT NULL DEFAULT true,
  source_system STRING        NOT NULL DEFAULT 'synthetic_generator',
  ingested_at   TIMESTAMP     NOT NULL DEFAULT current_timestamp(),
  CONSTRAINT products_pk PRIMARY KEY (product_id) NOT ENFORCED
)
USING DELTA
CLUSTER BY (product_id, category)
COMMENT 'Conformed product reference data used by transaction line items'
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.feature.allowColumnDefaults' = 'supported',
  'data_classification' = 'synthetic_product_data'
);

-- Transaction headers --------------------------------------------------------
CREATE TABLE IF NOT EXISTS `databricks-hackathon`.`00data`.`transactions` (
  transaction_id     STRING        NOT NULL COMMENT 'Stable transaction identifier',
  customer_id        STRING        NOT NULL COMMENT 'Customer that placed the transaction',
  transaction_ts     TIMESTAMP     NOT NULL COMMENT 'Timestamp at which the transaction occurred',
  transaction_date   DATE GENERATED ALWAYS AS (CAST(transaction_ts AS DATE)),
  channel            STRING        NOT NULL COMMENT 'Sales channel such as web, app, or store',
  store_id           STRING,
  currency_code      STRING        NOT NULL DEFAULT 'USD',
  subtotal_amount    DECIMAL(18,2) NOT NULL,
  discount_amount    DECIMAL(18,2) NOT NULL DEFAULT 0,
  tax_amount         DECIMAL(18,2) NOT NULL DEFAULT 0,
  total_amount       DECIMAL(18,2) NOT NULL,
  payment_method     STRING,
  transaction_status STRING        NOT NULL DEFAULT 'completed',
  source_system      STRING        NOT NULL DEFAULT 'synthetic_generator',
  ingested_at        TIMESTAMP     NOT NULL DEFAULT current_timestamp(),
  CONSTRAINT transactions_pk PRIMARY KEY (transaction_id) NOT ENFORCED
)
USING DELTA
CLUSTER BY (customer_id, transaction_date)
COMMENT 'Conformed transaction headers; customer_id logically references customers'
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.feature.allowColumnDefaults' = 'supported',
  'data_classification' = 'synthetic_transaction_data'
);

-- Transaction lines ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS `databricks-hackathon`.`00data`.`transaction_items` (
  transaction_id  STRING        NOT NULL COMMENT 'Transaction header identifier',
  line_number     INT           NOT NULL COMMENT 'One-based line number within a transaction',
  product_id      STRING        NOT NULL COMMENT 'Purchased product identifier',
  quantity        INT           NOT NULL,
  unit_price      DECIMAL(18,2) NOT NULL,
  discount_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  line_amount     DECIMAL(18,2) NOT NULL COMMENT 'Extended line amount after discount',
  ingested_at     TIMESTAMP     NOT NULL DEFAULT current_timestamp(),
  CONSTRAINT transaction_items_pk
    PRIMARY KEY (transaction_id, line_number) NOT ENFORCED
)
USING DELTA
CLUSTER BY (transaction_id, product_id)
COMMENT 'Conformed transaction line items; identifiers logically reference transactions and products'
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.feature.allowColumnDefaults' = 'supported',
  'data_classification' = 'synthetic_transaction_data'
);

-- Customer interactions -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `databricks-hackathon`.`00data`.`customer_events` (
  event_id         STRING    NOT NULL COMMENT 'Stable interaction identifier',
  customer_id      STRING    NOT NULL COMMENT 'Customer associated with the interaction',
  event_ts         TIMESTAMP NOT NULL,
  event_date       DATE GENERATED ALWAYS AS (CAST(event_ts AS DATE)),
  event_type       STRING    NOT NULL COMMENT 'Interaction type, such as login or cart_add',
  channel          STRING    NOT NULL COMMENT 'Originating channel, such as web, app, or support',
  session_id       STRING,
  product_id       STRING,
  campaign_id      STRING,
  event_properties MAP<STRING, STRING> COMMENT 'Sparse event-specific attributes',
  source_system    STRING    NOT NULL DEFAULT 'synthetic_generator',
  ingested_at      TIMESTAMP NOT NULL DEFAULT current_timestamp(),
  CONSTRAINT customer_events_pk PRIMARY KEY (event_id) NOT ENFORCED
)
USING DELTA
CLUSTER BY (customer_id, event_date)
COMMENT 'Conformed digital, campaign, and service interactions for customer feature engineering'
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.feature.allowColumnDefaults' = 'supported',
  'data_classification' = 'synthetic_engagement_data'
);

-- Point-in-time customer features -------------------------------------------
CREATE TABLE IF NOT EXISTS `databricks-hackathon`.`00data`.`customer_features` (
  customer_id                 STRING        NOT NULL,
  snapshot_date               DATE          NOT NULL COMMENT 'Date for which features are valid',
  days_since_last_purchase    INT,
  purchases_30d               INT           NOT NULL DEFAULT 0,
  purchases_90d               INT           NOT NULL DEFAULT 0,
  spend_30d                   DECIMAL(18,2) NOT NULL DEFAULT 0,
  spend_90d                   DECIMAL(18,2) NOT NULL DEFAULT 0,
  lifetime_value              DECIMAL(18,2) NOT NULL DEFAULT 0,
  average_order_value         DECIMAL(18,2),
  engagement_events_30d       INT           NOT NULL DEFAULT 0,
  recency_score               DOUBLE        COMMENT 'Normalized score from 0 to 1; higher is more recent',
  favorite_category           STRING,
  feature_version             STRING        NOT NULL COMMENT 'Version of the feature definition',
  computed_at                 TIMESTAMP     NOT NULL DEFAULT current_timestamp(),
  CONSTRAINT customer_features_pk
    PRIMARY KEY (customer_id, snapshot_date) NOT ENFORCED
)
USING DELTA
CLUSTER BY (customer_id, snapshot_date)
COMMENT 'Point-in-time customer features for analytics and model scoring'
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.feature.allowColumnDefaults' = 'supported',
  'data_classification' = 'derived_synthetic_customer_data'
);

-- Model outputs --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `databricks-hackathon`.`00data`.`customer_predictions` (
  prediction_id             STRING    NOT NULL COMMENT 'Stable identifier for this scoring event',
  customer_id               STRING    NOT NULL,
  scored_at                 TIMESTAMP NOT NULL,
  model_name                STRING    NOT NULL,
  model_version             STRING    NOT NULL,
  churn_probability         DOUBLE    COMMENT 'Probability from 0 to 1',
  purchase_propensity_score DOUBLE    COMMENT 'Probability from 0 to 1',
  predicted_next_category   STRING,
  prediction_horizon_days   INT,
  model_run_id              STRING    COMMENT 'MLflow run identifier when available',
  CONSTRAINT customer_predictions_pk PRIMARY KEY (prediction_id) NOT ENFORCED
)
USING DELTA
CLUSTER BY (customer_id, scored_at)
COMMENT 'Versioned churn and purchase-propensity model outputs'
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'data_classification' = 'derived_synthetic_customer_data'
);

-- Serving view ---------------------------------------------------------------
-- QUALIFY selects the most recent feature snapshot and model result without
-- duplicating customer attributes in another physical table.
CREATE OR REPLACE VIEW `databricks-hackathon`.`00data`.`customer_360`
COMMENT 'Current customer profile enriched with the latest features and prediction'
AS
WITH latest_features AS (
  SELECT *
  FROM `databricks-hackathon`.`00data`.`customer_features`
  QUALIFY row_number() OVER (
    PARTITION BY customer_id
    ORDER BY snapshot_date DESC, computed_at DESC
  ) = 1
),
latest_predictions AS (
  SELECT *
  FROM `databricks-hackathon`.`00data`.`customer_predictions`
  QUALIFY row_number() OVER (
    PARTITION BY customer_id
    ORDER BY scored_at DESC, prediction_id DESC
  ) = 1
)
SELECT
  c.customer_id,
  c.first_name,
  c.last_name,
  c.email,
  c.signup_date,
  c.segment,
  c.loyalty_tier,
  c.city,
  c.state_province,
  c.country_code,
  c.preferred_channel,
  c.marketing_opt_in,
  c.account_status,
  f.snapshot_date AS feature_snapshot_date,
  f.days_since_last_purchase,
  f.purchases_30d,
  f.purchases_90d,
  f.spend_30d,
  f.spend_90d,
  f.lifetime_value,
  f.average_order_value,
  f.engagement_events_30d,
  f.recency_score,
  f.favorite_category,
  p.scored_at AS prediction_scored_at,
  p.model_name,
  p.model_version,
  p.churn_probability,
  p.purchase_propensity_score,
  p.predicted_next_category
FROM `databricks-hackathon`.`00data`.`customers` AS c
LEFT JOIN latest_features AS f USING (customer_id)
LEFT JOIN latest_predictions AS p USING (customer_id);

-- Return the object locations for convenient confirmation in the SQL editor.
SELECT
  'databricks-hackathon' AS catalog_name,
  '00data' AS schema_name;
