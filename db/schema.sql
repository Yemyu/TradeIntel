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
