-- Exact validation gates for the deterministic seed-42 validation sample.

WITH item_rollup AS (
  SELECT
    transaction_id,
    round(sum(quantity * unit_price), 2) AS subtotal_amount,
    round(sum(discount_amount), 2) AS discount_amount
  FROM `databricks-hackathon`.`00data`.`transaction_items`
  GROUP BY transaction_id
),
checks AS (
  SELECT 'customers_row_count' AS check_name, 50L AS expected, count(*) AS actual
  FROM `databricks-hackathon`.`00data`.`customers`
  UNION ALL
  SELECT 'products_row_count', 40L, count(*)
  FROM `databricks-hackathon`.`00data`.`products`
  UNION ALL
  SELECT 'transactions_row_count', 1000L, count(*)
  FROM `databricks-hackathon`.`00data`.`transactions`
  UNION ALL
  SELECT 'transaction_items_row_count', 2500L, count(*)
  FROM `databricks-hackathon`.`00data`.`transaction_items`
  UNION ALL
  SELECT 'customer_events_row_count', 2000L, count(*)
  FROM `databricks-hackathon`.`00data`.`customer_events`
  UNION ALL
  SELECT 'customer_features_row_count', 50L, count(*)
  FROM `databricks-hackathon`.`00data`.`customer_features`
  UNION ALL
  SELECT 'customer_predictions_row_count', 50L, count(*)
  FROM `databricks-hackathon`.`00data`.`customer_predictions`
  UNION ALL
  SELECT 'customer_360_row_count', 50L, count(*)
  FROM `databricks-hackathon`.`00data`.`customer_360`
  UNION ALL
  SELECT 'customer_360_unique_customers', 50L, count(DISTINCT customer_id)
  FROM `databricks-hackathon`.`00data`.`customer_360`
  UNION ALL
  SELECT 'transactions_without_customer', 0L, count(*)
  FROM `databricks-hackathon`.`00data`.`transactions` AS t
  LEFT ANTI JOIN `databricks-hackathon`.`00data`.`customers` AS c USING (customer_id)
  UNION ALL
  SELECT 'items_without_transaction', 0L, count(*)
  FROM `databricks-hackathon`.`00data`.`transaction_items` AS i
  LEFT ANTI JOIN `databricks-hackathon`.`00data`.`transactions` AS t USING (transaction_id)
  UNION ALL
  SELECT 'items_without_product', 0L, count(*)
  FROM `databricks-hackathon`.`00data`.`transaction_items` AS i
  LEFT ANTI JOIN `databricks-hackathon`.`00data`.`products` AS p USING (product_id)
  UNION ALL
  SELECT 'events_without_customer', 0L, count(*)
  FROM `databricks-hackathon`.`00data`.`customer_events` AS e
  LEFT ANTI JOIN `databricks-hackathon`.`00data`.`customers` AS c USING (customer_id)
  UNION ALL
  SELECT 'customers_without_transaction', 0L, count(*)
  FROM `databricks-hackathon`.`00data`.`customers` AS c
  LEFT ANTI JOIN `databricks-hackathon`.`00data`.`transactions` AS t USING (customer_id)
  UNION ALL
  SELECT 'customers_without_event', 0L, count(*)
  FROM `databricks-hackathon`.`00data`.`customers` AS c
  LEFT ANTI JOIN `databricks-hackathon`.`00data`.`customer_events` AS e USING (customer_id)
  UNION ALL
  SELECT 'transaction_amount_mismatches', 0L, count(*)
  FROM `databricks-hackathon`.`00data`.`transactions` AS t
  JOIN item_rollup AS i USING (transaction_id)
  WHERE
    abs(t.subtotal_amount - i.subtotal_amount) > 0.01
    OR abs(t.discount_amount - i.discount_amount) > 0.01
    OR abs(t.tax_amount - round((i.subtotal_amount - i.discount_amount) * 0.08, 2)) > 0.01
    OR abs(t.total_amount - (i.subtotal_amount - i.discount_amount + t.tax_amount)) > 0.01
  UNION ALL
  SELECT 'transactions_before_signup', 0L, count(*)
  FROM `databricks-hackathon`.`00data`.`transactions` AS t
  JOIN `databricks-hackathon`.`00data`.`customers` AS c USING (customer_id)
  WHERE CAST(t.transaction_ts AS DATE) < c.signup_date
  UNION ALL
  SELECT 'events_before_signup', 0L, count(*)
  FROM `databricks-hackathon`.`00data`.`customer_events` AS e
  JOIN `databricks-hackathon`.`00data`.`customers` AS c USING (customer_id)
  WHERE CAST(e.event_ts AS DATE) < c.signup_date
)
SELECT
  check_name,
  expected,
  actual,
  CASE WHEN expected = actual THEN 'PASS' ELSE 'FAIL' END AS status
FROM checks
ORDER BY check_name;
