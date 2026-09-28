-- TradeIntel MySQL schema
-- This file is intentionally additive: it never drops or truncates tables.

CREATE DATABASE IF NOT EXISTS tradeintel
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE tradeintel;

CREATE TABLE IF NOT EXISTS policy_event (
    policy_id VARCHAR(64) NOT NULL,
    policy_name VARCHAR(255) NOT NULL,
    importer_name VARCHAR(128) NOT NULL,
    target_origin_name VARCHAR(128) NOT NULL,
    target_origin_code CHAR(4) NULL,
    announcement_date DATE NOT NULL,
    effective_date DATE NOT NULL,
    additional_rate DECIMAL(8, 6) NOT NULL,
    source_url VARCHAR(2048) NOT NULL,
    PRIMARY KEY (policy_id),
    CONSTRAINT chk_policy_rate_nonnegative CHECK (additional_rate >= 0),
    CONSTRAINT chk_policy_dates CHECK (effective_date >= announcement_date)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS policy_product (
    policy_id VARCHAR(64) NOT NULL,
    canonical_hts8 CHAR(8) NOT NULL,
    raw_hts VARCHAR(16) NOT NULL,
    source_annex VARCHAR(64) NOT NULL,
    source_page SMALLINT UNSIGNED NOT NULL,
    amended BOOLEAN NOT NULL,
    amendment_source_page SMALLINT UNSIGNED NULL,
    source_url VARCHAR(2048) NOT NULL,
    amendment_source_url VARCHAR(2048) NULL,
    exclusion_status VARCHAR(64) NOT NULL,
    PRIMARY KEY (policy_id, canonical_hts8),
    CONSTRAINT fk_product_policy
        FOREIGN KEY (policy_id) REFERENCES policy_event (policy_id),
    CONSTRAINT chk_policy_product_hts8 CHECK (canonical_hts8 REGEXP '^[0-9]{8}$')
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS trade_monthly (
    year SMALLINT UNSIGNED NOT NULL,
    month TINYINT UNSIGNED NOT NULL,
    origin_code CHAR(4) NOT NULL,
    origin_name VARCHAR(128) NOT NULL,
    hts10 CHAR(10) NOT NULL,
    hts8 CHAR(8) NOT NULL,
    import_value_consumption_usd DECIMAL(20, 0) NOT NULL,
    detail_row_count INT UNSIGNED NOT NULL,
    source_url VARCHAR(2048) NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (year, month, origin_code, hts10),
    KEY idx_trade_hts8 (hts8),
    KEY idx_trade_origin_month (origin_code, year, month),
    CONSTRAINT chk_trade_month CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT chk_trade_value_nonnegative CHECK (import_value_consumption_usd >= 0),
    CONSTRAINT chk_trade_detail_rows_nonnegative CHECK (detail_row_count >= 0),
    CONSTRAINT chk_trade_hts8 CHECK (hts8 REGEXP '^[0-9]{8}$')
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS origin_dimension (
    origin_code CHAR(4) NOT NULL,
    canonical_origin_name VARCHAR(128) NOT NULL,
    observed_origin_names VARCHAR(512) NOT NULL,
    first_observed_month CHAR(7) NOT NULL,
    last_observed_month CHAR(7) NOT NULL,
    name_variant_count SMALLINT UNSIGNED NOT NULL,
    canonical_name_method VARCHAR(64) NOT NULL,
    quality_status VARCHAR(64) NOT NULL,
    reference_url VARCHAR(2048) NOT NULL,
    PRIMARY KEY (origin_code),
    CONSTRAINT chk_origin_code CHECK (origin_code REGEXP '^[0-9]{4}$'),
    CONSTRAINT chk_origin_months CHECK (
        first_observed_month REGEXP '^[0-9]{4}-[0-9]{2}$'
        AND last_observed_month REGEXP '^[0-9]{4}-[0-9]{2}$'
    ),
    CONSTRAINT chk_origin_name_variants CHECK (name_variant_count >= 1)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS policy_origin_mapping (
    policy_id VARCHAR(64) NOT NULL,
    policy_target_origin_name VARCHAR(128) NOT NULL,
    origin_code CHAR(4) NOT NULL,
    canonical_origin_name VARCHAR(128) NOT NULL,
    mapping_method VARCHAR(128) NOT NULL,
    quality_status VARCHAR(64) NOT NULL,
    reference_url VARCHAR(2048) NOT NULL,
    PRIMARY KEY (policy_id),
    CONSTRAINT fk_policy_origin_policy
        FOREIGN KEY (policy_id) REFERENCES policy_event (policy_id),
    CONSTRAINT fk_policy_origin_code
        FOREIGN KEY (origin_code) REFERENCES origin_dimension (origin_code)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS hts8_coverage (
    policy_id VARCHAR(64) NOT NULL,
    canonical_hts8 CHAR(8) NOT NULL,
    observed_trade_row_count BIGINT UNSIGNED NOT NULL,
    observed_month_count TINYINT UNSIGNED NOT NULL,
    first_observed_month CHAR(7) NULL,
    last_observed_month CHAR(7) NULL,
    total_import_value_consumption_usd DECIMAL(20, 0) NOT NULL,
    coverage_status VARCHAR(64) NOT NULL,
    policy_source_url VARCHAR(2048) NOT NULL,
    classification_reference_url VARCHAR(2048) NOT NULL,
    PRIMARY KEY (policy_id, canonical_hts8),
    CONSTRAINT fk_coverage_policy_product
        FOREIGN KEY (policy_id, canonical_hts8)
        REFERENCES policy_product (policy_id, canonical_hts8),
    CONSTRAINT chk_coverage_hts8 CHECK (canonical_hts8 REGEXP '^[0-9]{8}$'),
    CONSTRAINT chk_coverage_month_count CHECK (observed_month_count <= 48)
) ENGINE = InnoDB;

-- Generic trade data is additive.  It does not replace the historical
-- policy-specific trade_monthly table above.  The file snapshot remains the
-- reproducible release; rows in MySQL are a query copy of that release.
CREATE TABLE IF NOT EXISTS trade_dataset_release (
    dataset_id VARCHAR(80) NOT NULL,
    data_version CHAR(64) NOT NULL,
    reporter CHAR(2) NOT NULL,
    flow VARCHAR(8) NOT NULL,
    classification VARCHAR(32) NOT NULL,
    metric VARCHAR(80) NOT NULL,
    source_manifest_sha256 CHAR(64) NOT NULL,
    published_at_utc DATETIME NOT NULL,
    PRIMARY KEY (dataset_id, data_version),
    CONSTRAINT chk_dataset_flow CHECK (flow IN ('import', 'export')),
    CONSTRAINT chk_dataset_version CHECK (data_version REGEXP '^[0-9a-f]{64}$')
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS trade_dataset_month (
    dataset_id VARCHAR(80) NOT NULL,
    data_version CHAR(64) NOT NULL,
    year SMALLINT UNSIGNED NOT NULL,
    month TINYINT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    source_url VARCHAR(2048) NULL,
    source_sha256 CHAR(64) NULL,
    processed_sha256 CHAR(64) NULL,
    row_count INT UNSIGNED NULL,
    PRIMARY KEY (dataset_id, data_version, year, month),
    CONSTRAINT fk_trade_month_release FOREIGN KEY (dataset_id, data_version)
        REFERENCES trade_dataset_release (dataset_id, data_version),
    CONSTRAINT chk_dataset_month CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT chk_dataset_month_status CHECK
        (status IN ('raw_only', 'queryable_aggregate', 'queryable_detail'))
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS trade_import_hts10_monthly (
    dataset_id VARCHAR(80) NOT NULL,
    data_version CHAR(64) NOT NULL,
    year SMALLINT UNSIGNED NOT NULL,
    month TINYINT UNSIGNED NOT NULL,
    reporter CHAR(2) NOT NULL,
    flow VARCHAR(8) NOT NULL,
    classification VARCHAR(32) NOT NULL,
    hts10 CHAR(10) NOT NULL,
    partner_key VARCHAR(20) NOT NULL,
    import_value_consumption_usd DECIMAL(20, 0) NULL,
    observed BOOLEAN NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (dataset_id, data_version, year, month, reporter,
                 flow, classification, hts10, partner_key),
    KEY idx_trade_product_period (data_version, hts10, year, month),
    CONSTRAINT fk_trade_product_month FOREIGN KEY
        (dataset_id, data_version, year, month)
        REFERENCES trade_dataset_month (dataset_id, data_version, year, month),
    CONSTRAINT chk_trade_import_flow CHECK (flow = 'import'),
    CONSTRAINT chk_trade_product_hts10 CHECK (hts10 REGEXP '^[0-9]{10}$'),
    CONSTRAINT chk_trade_product_value CHECK
        ((observed = 0 AND import_value_consumption_usd IS NULL)
         OR (observed = 1 AND import_value_consumption_usd IS NOT NULL
             AND import_value_consumption_usd >= 0))
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS trade_export_scheduleb10_monthly (
    dataset_id VARCHAR(80) NOT NULL,
    data_version CHAR(64) NOT NULL,
    year SMALLINT UNSIGNED NOT NULL,
    month TINYINT UNSIGNED NOT NULL,
    scheduleb10 CHAR(10) NOT NULL,
    partner_code CHAR(4) NOT NULL,
    domestic_export_fas_usd DECIMAL(20, 0) NULL,
    foreign_reexport_fas_usd DECIMAL(20, 0) NULL,
    total_export_fas_usd DECIMAL(20, 0) NOT NULL,
    domestic_observed BOOLEAN NOT NULL,
    foreign_observed BOOLEAN NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (dataset_id, data_version, year, month, scheduleb10, partner_code),
    KEY idx_trade_export_product_period (data_version, scheduleb10, year, month),
    KEY idx_trade_export_partner_period (data_version, partner_code, year, month),
    CONSTRAINT fk_trade_export_product_month FOREIGN KEY
        (dataset_id, data_version, year, month)
        REFERENCES trade_dataset_month (dataset_id, data_version, year, month),
    CONSTRAINT chk_trade_export_month CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT chk_trade_export_scheduleb10 CHECK (scheduleb10 REGEXP '^[0-9]{10}$'),
    CONSTRAINT chk_trade_export_partner CHECK (partner_code REGEXP '^[0-9]{4}$'),
    CONSTRAINT chk_trade_export_source_sha CHECK (source_sha256 REGEXP '^[0-9a-f]{64}$'),
    CONSTRAINT chk_trade_export_domestic CHECK
        ((domestic_observed = 0 AND domestic_export_fas_usd IS NULL)
         OR (domestic_observed = 1 AND domestic_export_fas_usd IS NOT NULL
             AND domestic_export_fas_usd >= 0)),
    CONSTRAINT chk_trade_export_foreign CHECK
        ((foreign_observed = 0 AND foreign_reexport_fas_usd IS NULL)
         OR (foreign_observed = 1 AND foreign_reexport_fas_usd IS NOT NULL
             AND foreign_reexport_fas_usd >= 0)),
    CONSTRAINT chk_trade_export_any_observed CHECK
        (domestic_observed = 1 OR foreign_observed = 1),
    CONSTRAINT chk_trade_export_total CHECK
        (total_export_fas_usd = COALESCE(domestic_export_fas_usd, 0)
                               + COALESCE(foreign_reexport_fas_usd, 0))
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS trade_mysql_mirror_verification (
    dataset_id VARCHAR(80) NOT NULL,
    data_version CHAR(64) NOT NULL,
    source_manifest_sha256 CHAR(64) NOT NULL,
    verified_month_count SMALLINT UNSIGNED NOT NULL,
    csv_row_count BIGINT UNSIGNED NOT NULL,
    expected_sql_row_count BIGINT UNSIGNED NOT NULL,
    verified_sql_row_count BIGINT UNSIGNED NOT NULL,
    audit_sha256 CHAR(64) NOT NULL,
    verified_at_utc DATETIME NOT NULL,
    PRIMARY KEY (dataset_id, data_version),
    CONSTRAINT fk_trade_mirror_verification_release FOREIGN KEY
        (dataset_id, data_version)
        REFERENCES trade_dataset_release (dataset_id, data_version),
    CONSTRAINT chk_trade_mirror_manifest_sha CHECK
        (source_manifest_sha256 REGEXP '^[0-9a-f]{64}$'),
    CONSTRAINT chk_trade_mirror_audit_sha CHECK
        (audit_sha256 REGEXP '^[0-9a-f]{64}$'),
    CONSTRAINT chk_trade_mirror_months CHECK (verified_month_count > 0),
    CONSTRAINT chk_trade_mirror_row_counts CHECK
        (expected_sql_row_count = verified_sql_row_count)
) ENGINE = InnoDB;
