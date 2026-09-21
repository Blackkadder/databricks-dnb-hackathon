-- Databricks requires Delta CHECK constraints to be added after CREATE TABLE.
-- Run this once during initial provisioning, after 00_create_customer_data.sql.

ALTER TABLE `databricks-hackathon`.`00data`.`customers`
ADD CONSTRAINT customers_account_status_chk
CHECK (account_status IN ('active', 'inactive', 'suspended', 'closed'));

ALTER TABLE `databricks-hackathon`.`00data`.`customers`
ADD CONSTRAINT customers_loyalty_tier_chk
CHECK (
  loyalty_tier IS NULL
  OR loyalty_tier IN ('none', 'bronze', 'silver', 'gold', 'platinum')
);

ALTER TABLE `databricks-hackathon`.`00data`.`customers`
ADD CONSTRAINT customers_country_code_chk
CHECK (country_code IS NULL OR length(country_code) = 2);

ALTER TABLE `databricks-hackathon`.`00data`.`products`
ADD CONSTRAINT products_unit_cost_chk
CHECK (unit_cost IS NULL OR unit_cost >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`products`
ADD CONSTRAINT products_list_price_chk
CHECK (list_price >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`transactions`
ADD CONSTRAINT transactions_currency_code_chk
CHECK (length(currency_code) = 3);

ALTER TABLE `databricks-hackathon`.`00data`.`transactions`
ADD CONSTRAINT transactions_subtotal_chk
CHECK (subtotal_amount >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`transactions`
ADD CONSTRAINT transactions_discount_chk
CHECK (discount_amount >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`transactions`
ADD CONSTRAINT transactions_tax_chk
CHECK (tax_amount >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`transactions`
ADD CONSTRAINT transactions_total_chk
CHECK (total_amount >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`transactions`
ADD CONSTRAINT transactions_status_chk
CHECK (transaction_status IN ('pending', 'completed', 'cancelled', 'refunded'));

ALTER TABLE `databricks-hackathon`.`00data`.`transaction_items`
ADD CONSTRAINT transaction_items_line_number_chk
CHECK (line_number > 0);

ALTER TABLE `databricks-hackathon`.`00data`.`transaction_items`
ADD CONSTRAINT transaction_items_quantity_chk
CHECK (quantity > 0);

ALTER TABLE `databricks-hackathon`.`00data`.`transaction_items`
ADD CONSTRAINT transaction_items_unit_price_chk
CHECK (unit_price >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`transaction_items`
ADD CONSTRAINT transaction_items_discount_chk
CHECK (discount_amount >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`transaction_items`
ADD CONSTRAINT transaction_items_line_amount_chk
CHECK (line_amount >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`customer_features`
ADD CONSTRAINT customer_features_recency_days_chk
CHECK (days_since_last_purchase IS NULL OR days_since_last_purchase >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`customer_features`
ADD CONSTRAINT customer_features_purchase_counts_chk
CHECK (purchases_30d >= 0 AND purchases_90d >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`customer_features`
ADD CONSTRAINT customer_features_spend_chk
CHECK (spend_30d >= 0 AND spend_90d >= 0 AND lifetime_value >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`customer_features`
ADD CONSTRAINT customer_features_aov_chk
CHECK (average_order_value IS NULL OR average_order_value >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`customer_features`
ADD CONSTRAINT customer_features_engagement_chk
CHECK (engagement_events_30d >= 0);

ALTER TABLE `databricks-hackathon`.`00data`.`customer_features`
ADD CONSTRAINT customer_features_recency_score_chk
CHECK (recency_score IS NULL OR recency_score BETWEEN 0 AND 1);

ALTER TABLE `databricks-hackathon`.`00data`.`customer_predictions`
ADD CONSTRAINT customer_predictions_churn_chk
CHECK (churn_probability IS NULL OR churn_probability BETWEEN 0 AND 1);

ALTER TABLE `databricks-hackathon`.`00data`.`customer_predictions`
ADD CONSTRAINT customer_predictions_propensity_chk
CHECK (
  purchase_propensity_score IS NULL
  OR purchase_propensity_score BETWEEN 0 AND 1
);

ALTER TABLE `databricks-hackathon`.`00data`.`customer_predictions`
ADD CONSTRAINT customer_predictions_horizon_chk
CHECK (prediction_horizon_days IS NULL OR prediction_horizon_days > 0);
