-- Gas Price Dashboard — local development schema
-- Matches the production RDS schema exactly.
-- Mounted into postgres container via /docker-entrypoint-initdb.d/

-- Raw weekly prices (one row per state/PADD-region per week)
-- state column holds either a 2-char state abbreviation (e.g. 'CA')
-- or a 3-char PADD region code (e.g. 'R20') for states without individual EIA data.
CREATE TABLE IF NOT EXISTS prices_weekly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(10)   NOT NULL,
    week_start  DATE          NOT NULL,
    avg_price   NUMERIC(5,3)  NOT NULL,
    grade       VARCHAR(20)   NOT NULL DEFAULT 'regular',
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (state, week_start, grade)
);

-- Monthly rollup
CREATE TABLE IF NOT EXISTS prices_monthly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(10)   NOT NULL,
    year_month  DATE          NOT NULL,
    avg_price   NUMERIC(5,3)  NOT NULL,
    min_price   NUMERIC(5,3)  NOT NULL,
    max_price   NUMERIC(5,3)  NOT NULL,
    grade       VARCHAR(20)   NOT NULL DEFAULT 'regular',
    UNIQUE (state, year_month, grade)
);

-- Yearly rollup
CREATE TABLE IF NOT EXISTS prices_yearly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(10)   NOT NULL,
    year        SMALLINT      NOT NULL,
    avg_price   NUMERIC(5,3)  NOT NULL,
    min_price   NUMERIC(5,3)  NOT NULL,
    max_price   NUMERIC(5,3)  NOT NULL,
    grade       VARCHAR(20)   NOT NULL DEFAULT 'regular',
    UNIQUE (state, year, grade)
);

-- ETL audit log
CREATE TABLE IF NOT EXISTS ingest_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    status           VARCHAR(20) NOT NULL,
    records_fetched  INT,
    error_message    TEXT,
    s3_path          TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS ON prices_weekly (state, week_start DESC);
CREATE INDEX IF NOT EXISTS ON prices_monthly (state, year_month DESC);
CREATE INDEX IF NOT EXISTS ON prices_yearly (state, year DESC);
