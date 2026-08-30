-- Verify the audited country and HTS coverage reference tables.

USE tradeintel;

-- 1. How many stable origin codes were observed?
SELECT COUNT(*) AS origin_code_count FROM origin_dimension;

-- 2. Which codes have historical name changes?
SELECT origin_code, canonical_origin_name, observed_origin_names
FROM origin_dimension
WHERE name_variant_count > 1
ORDER BY origin_code;

-- 3. Does every policy target map to an existing origin code?
SELECT COUNT(*) AS invalid_policy_origin_mappings
FROM policy_origin_mapping m
LEFT JOIN policy_event e ON e.policy_id = m.policy_id
LEFT JOIN origin_dimension o ON o.origin_code = m.origin_code
WHERE e.policy_id IS NULL OR o.origin_code IS NULL;

-- 4. Which policy codes have no observed trade rows?
SELECT policy_id, canonical_hts8, coverage_status
FROM hts8_coverage
WHERE coverage_status <> 'observed'
ORDER BY policy_id, canonical_hts8;

-- 5. Do coverage counts agree with the policy-product table?
SELECT
    (SELECT COUNT(*) FROM policy_product) AS policy_product_rows,
    (SELECT COUNT(*) FROM hts8_coverage) AS coverage_rows;

-- 6. Does the policy event use the audited target-origin code?
SELECT e.policy_id, e.target_origin_code, m.origin_code AS mapped_origin_code,
       e.target_origin_code = m.origin_code AS codes_agree
FROM policy_event e
JOIN policy_origin_mapping m ON m.policy_id = e.policy_id;
