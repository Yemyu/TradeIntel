-- Ten beginner-friendly verification queries.
-- Run after loading data with: mysql --login-path=tradeintel tradeintel < this_file

USE tradeintel;

-- 1. How many rows are in each table?
SELECT 'policy_event' AS table_name, COUNT(*) AS row_count FROM policy_event
UNION ALL
SELECT 'policy_product', COUNT(*) FROM policy_product
UNION ALL
SELECT 'trade_monthly', COUNT(*) FROM trade_monthly;

-- 2. What policy event did we load?
SELECT policy_id, policy_name, target_origin_name, target_origin_code,
       effective_date, additional_rate
FROM policy_event;

-- 3. Did all policy products point to a real policy?
SELECT COUNT(*) AS orphan_policy_products
FROM policy_product p
LEFT JOIN policy_event e ON e.policy_id = p.policy_id
WHERE e.policy_id IS NULL;

-- 4. What months does the trade table cover?
SELECT MIN(year * 100 + month) AS first_yyyymm,
       MAX(year * 100 + month) AS last_yyyymm,
       COUNT(DISTINCT year * 100 + month) AS month_count
FROM trade_monthly;

-- 5. Did the composite primary key prevent duplicate observations?
SELECT year, month, origin_code, hts10, COUNT(*) AS duplicate_count
FROM trade_monthly
GROUP BY year, month, origin_code, hts10
HAVING COUNT(*) > 1;

-- 6. How many policy HTS8 codes have trade observations?
SELECT COUNT(DISTINCT p.canonical_hts8) AS policy_codes_with_trade_rows
FROM policy_product p
JOIN trade_monthly t ON t.hts8 = p.canonical_hts8;

-- 7. What was the target-origin value in the transition month?
SELECT t.year, t.month, e.target_origin_name,
       SUM(t.import_value_consumption_usd) AS target_value_usd
FROM trade_monthly t
JOIN policy_product p ON p.canonical_hts8 = t.hts8
JOIN policy_event e ON e.policy_id = p.policy_id
WHERE t.year = 2018 AND t.month = 7
  AND t.origin_code = e.target_origin_code
GROUP BY t.year, t.month, e.target_origin_name;

-- 8. What are the pre/transition/post totals by origin group?
SELECT CASE
           WHEN (t.year * 100 + t.month) < 201807 THEN 'pre'
           WHEN (t.year * 100 + t.month) = 201807 THEN 'transition'
           ELSE 'post'
       END AS period,
       CASE WHEN t.origin_code = e.target_origin_code
            THEN 'target_origin' ELSE 'other_origins' END AS origin_group,
       SUM(t.import_value_consumption_usd) AS value_usd
FROM trade_monthly t
JOIN policy_product p ON p.canonical_hts8 = t.hts8
JOIN policy_event e ON e.policy_id = p.policy_id
GROUP BY period, origin_group
ORDER BY period, origin_group;

-- 9. Which five origins have the largest value in the transition month?
SELECT t.origin_code, t.origin_name,
       SUM(t.import_value_consumption_usd) AS value_usd
FROM trade_monthly t
JOIN policy_product p ON p.canonical_hts8 = t.hts8
WHERE t.year = 2018 AND t.month = 7
GROUP BY t.origin_code, t.origin_name
ORDER BY value_usd DESC
LIMIT 5;

-- 10. Are all source fingerprints well-formed SHA-256 values?
SELECT COUNT(*) AS invalid_source_hashes
FROM trade_monthly
WHERE source_sha256 NOT REGEXP '^[0-9a-fA-F]{64}$';
