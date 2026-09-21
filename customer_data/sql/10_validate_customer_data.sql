-- Post-load checks for the customer data model.
-- Run this file after loading data.

-- Inventory ------------------------------------------------------------------
SHOW TABLES IN `databricks-hackathon`.`00data`;

-- Row counts. The hackathon requirement is at least 10,000 customer profiles. -
SELECT 'customers' AS object_name, count(*) AS row_count
FROM `databricks-hackathon`.`00data`.`customers`
UNION ALL
SELECT 'products', count(*)
FROM `databricks-hackathon`.`00data`.`products`
UNION ALL
SELECT 'transactions', count(*)
FROM `databricks-hackathon`.`00data`.`transactions`
UNION ALL
SELECT 'transaction_items', count(*)
FROM `databricks-hackathon`.`00data`.`transaction_items`
UNION ALL
SELECT 'customer_events', count(*)
FROM `databricks-hackathon`.`00data`.`customer_events`
UNION ALL
SELECT 'customer_features', count(*)
FROM `databricks-hackathon`.`00data`.`customer_features`
UNION ALL
SELECT 'customer_predictions', count(*)
FROM `databricks-hackathon`.`00data`.`customer_predictions`;

-- Duplicate informational primary keys. Each result should return zero rows. --
SELECT customer_id, count(*) AS duplicate_count
FROM `databricks-hackathon`.`00data`.`customers`
GROUP BY customer_id
HAVING count(*) > 1;

SELECT transaction_id, count(*) AS duplicate_count
FROM `databricks-hackathon`.`00data`.`transactions`
GROUP BY transaction_id
HAVING count(*) > 1;

SELECT transaction_id, line_number, count(*) AS duplicate_count
FROM `databricks-hackathon`.`00data`.`transaction_items`
GROUP BY transaction_id, line_number
HAVING count(*) > 1;

SELECT customer_id, snapshot_date, count(*) AS duplicate_count
FROM `databricks-hackathon`.`00data`.`customer_features`
GROUP BY customer_id, snapshot_date
HAVING count(*) > 1;

-- Orphan relationships. Each result should return a count of zero. ------------
SELECT count(*) AS transactions_without_customer
FROM `databricks-hackathon`.`00data`.`transactions` AS t
LEFT ANTI JOIN `databricks-hackathon`.`00data`.`customers` AS c USING (customer_id);

SELECT count(*) AS items_without_transaction
FROM `databricks-hackathon`.`00data`.`transaction_items` AS i
LEFT ANTI JOIN `databricks-hackathon`.`00data`.`transactions` AS t USING (transaction_id);

SELECT count(*) AS items_without_product
FROM `databricks-hackathon`.`00data`.`transaction_items` AS i
LEFT ANTI JOIN `databricks-hackathon`.`00data`.`products` AS p USING (product_id);

SELECT count(*) AS events_without_customer
FROM `databricks-hackathon`.`00data`.`customer_events` AS e
LEFT ANTI JOIN `databricks-hackathon`.`00data`.`customers` AS c USING (customer_id);

SELECT count(*) AS features_without_customer
FROM `databricks-hackathon`.`00data`.`customer_features` AS f
LEFT ANTI JOIN `databricks-hackathon`.`00data`.`customers` AS c USING (customer_id);

SELECT count(*) AS predictions_without_customer
FROM `databricks-hackathon`.`00data`.`customer_predictions` AS p
LEFT ANTI JOIN `databricks-hackathon`.`00data`.`customers` AS c USING (customer_id);

-- Coverage of the three required customer signals. ---------------------------
SELECT
  count(*) AS customer_count,
  count_if(recency_score IS NOT NULL) AS customers_with_recency_score,
  count_if(churn_probability IS NOT NULL) AS customers_with_churn_probability,
  count_if(purchase_propensity_score IS NOT NULL) AS customers_with_propensity
FROM `databricks-hackathon`.`00data`.`customer_360`;
