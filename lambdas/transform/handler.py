"""
Lambda entry point for the EIA gas price transform function.

Triggered by S3 ObjectCreated on the raw/ prefix.

Flow:
  1. Parse S3 event to get bucket + key.
  2. Fetch DB password and Redis URL from Secrets Manager.
  3. Cold-start: build SQLAlchemy engine, run CREATE TABLE IF NOT EXISTS.
  4. Read and validate raw JSON from S3.
  5. Filter to state-level duoarea codes, build TransformRecords.
  6. Compute weekly / monthly / yearly aggregates.
  7. Upsert all three tables + write ingest_log in one transaction.
  8. Invalidate Redis cache keys matching 'prices:*' via SCAN + DEL.
  9. Return summary dict.

Re-raises on failure so Lambda marks the invocation failed.
Redis invalidation failure is non-fatal — a stale cache is acceptable but
a failed DB write should not silently succeed.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text, Engine

from aggregator import build_weekly, build_monthly, build_yearly
from models import S3Payload, TransformRecord

# ---------------------------------------------------------------------------
# Structured logging — same pattern as the ingest Lambda
# ---------------------------------------------------------------------------

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def log(level: int, event: str, **kwargs: Any) -> None:
    logger.log(
        level,
        json.dumps({
            "event": event,
            "function": os.environ.get("AWS_LAMBDA_FUNCTION_NAME"),
            **kwargs,
        }),
    )


# ---------------------------------------------------------------------------
# AWS clients — module-level for Lambda warm-start reuse
# ---------------------------------------------------------------------------

_secrets_client = boto3.client("secretsmanager")
_s3_client = boto3.client("s3")

# SQLAlchemy engine is None until the first cold-start invocation
_engine: Engine | None = None
_db_initialised: bool = False


def _get_secret(secret_arn: str) -> str:
    try:
        response = _secrets_client.get_secret_value(SecretId=secret_arn)
    except ClientError as exc:
        log(logging.ERROR, "secrets_manager_error", secret=secret_arn, error=str(exc))
        raise
    return response["SecretString"]


# ---------------------------------------------------------------------------
# DB schema initialisation (runs once per Lambda container lifetime)
# ---------------------------------------------------------------------------

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS prices_weekly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(2)   NOT NULL,
    week_start  DATE         NOT NULL,
    avg_price   NUMERIC(5,3) NOT NULL,
    grade       VARCHAR(20)  NOT NULL DEFAULT 'regular',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (state, week_start, grade)
);

CREATE TABLE IF NOT EXISTS prices_monthly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(2)   NOT NULL,
    year_month  DATE         NOT NULL,
    avg_price   NUMERIC(5,3) NOT NULL,
    min_price   NUMERIC(5,3) NOT NULL,
    max_price   NUMERIC(5,3) NOT NULL,
    grade       VARCHAR(20)  NOT NULL DEFAULT 'regular',
    UNIQUE (state, year_month, grade)
);

CREATE TABLE IF NOT EXISTS prices_yearly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(2)   NOT NULL,
    year        SMALLINT     NOT NULL,
    avg_price   NUMERIC(5,3) NOT NULL,
    min_price   NUMERIC(5,3) NOT NULL,
    max_price   NUMERIC(5,3) NOT NULL,
    grade       VARCHAR(20)  NOT NULL DEFAULT 'regular',
    UNIQUE (state, year, grade)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          VARCHAR(20) NOT NULL,
    records_fetched INT,
    error_message   TEXT,
    s3_path         TEXT
);
"""


def _build_engine(db_password: str) -> Engine:
    host = os.environ["DB_HOST"]
    name = os.environ["DB_NAME"]
    user = os.environ["DB_USERNAME"]
    port = os.environ.get("DB_PORT", "5432")
    url = f"postgresql+psycopg2://{user}:{db_password}@{host}:{port}/{name}"
    return create_engine(
        url,
        pool_size=1,        # Lambda: one connection per container
        max_overflow=0,
        pool_pre_ping=True, # recover from idle-timeout disconnects on warm starts
        connect_args={
            "connect_timeout": 10,
            "sslmode": "require",  # RDS enforces TLS
        },
    )


def _ensure_db_initialised(engine: Engine) -> None:
    global _db_initialised
    if _db_initialised:
        return
    log(logging.INFO, "db_init_start")
    with engine.begin() as conn:
        conn.execute(text(_CREATE_TABLES_SQL))
    _db_initialised = True
    log(logging.INFO, "db_init_complete")


# ---------------------------------------------------------------------------
# S3 event parsing
# ---------------------------------------------------------------------------

def _parse_s3_event(event: dict[str, Any]) -> tuple[str, str]:
    """Extract (bucket, key) from a standard S3 ObjectCreated event."""
    record = event["Records"][0]["s3"]
    bucket = record["bucket"]["name"]
    # S3 URL-encodes special characters in the key within the event notification
    key = urllib.parse.unquote_plus(record["object"]["key"])
    return bucket, key


# ---------------------------------------------------------------------------
# Upsert helpers (SQLAlchemy 2.x text() + executemany via list of dicts)
# ---------------------------------------------------------------------------

def _upsert_weekly(conn: Any, rows: list) -> int:
    if not rows:
        return 0
    conn.execute(
        text("""
            INSERT INTO prices_weekly (state, week_start, avg_price, grade)
            VALUES (:state, :week_start, :avg_price, :grade)
            ON CONFLICT (state, week_start, grade)
            DO UPDATE SET avg_price = EXCLUDED.avg_price
        """),
        [{"state": r.state, "week_start": r.week_start,
          "avg_price": r.avg_price, "grade": r.grade} for r in rows],
    )
    return len(rows)


def _upsert_monthly(conn: Any, rows: list) -> int:
    if not rows:
        return 0
    conn.execute(
        text("""
            INSERT INTO prices_monthly (state, year_month, avg_price, min_price, max_price, grade)
            VALUES (:state, :year_month, :avg_price, :min_price, :max_price, :grade)
            ON CONFLICT (state, year_month, grade)
            DO UPDATE SET
                avg_price = EXCLUDED.avg_price,
                min_price = EXCLUDED.min_price,
                max_price = EXCLUDED.max_price
        """),
        [{"state": r.state, "year_month": r.year_month, "avg_price": r.avg_price,
          "min_price": r.min_price, "max_price": r.max_price, "grade": r.grade} for r in rows],
    )
    return len(rows)


def _upsert_yearly(conn: Any, rows: list) -> int:
    if not rows:
        return 0
    conn.execute(
        text("""
            INSERT INTO prices_yearly (state, year, avg_price, min_price, max_price, grade)
            VALUES (:state, :year, :avg_price, :min_price, :max_price, :grade)
            ON CONFLICT (state, year, grade)
            DO UPDATE SET
                avg_price = EXCLUDED.avg_price,
                min_price = EXCLUDED.min_price,
                max_price = EXCLUDED.max_price
        """),
        [{"state": r.state, "year": r.year, "avg_price": r.avg_price,
          "min_price": r.min_price, "max_price": r.max_price, "grade": r.grade} for r in rows],
    )
    return len(rows)


def _write_ingest_log(
    conn: Any,
    status: str,
    records_fetched: int | None,
    s3_path: str,
    error_message: str | None = None,
) -> None:
    conn.execute(
        text("""
            INSERT INTO ingest_log (status, records_fetched, s3_path, error_message)
            VALUES (:status, :records_fetched, :s3_path, :error_message)
        """),
        {"status": status, "records_fetched": records_fetched,
         "s3_path": s3_path, "error_message": error_message},
    )


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    global _engine

    log(logging.INFO, "transform_start")

    # --- Parse S3 event -------------------------------------------------------
    try:
        bucket, key = _parse_s3_event(event)
    except (KeyError, IndexError) as exc:
        log(logging.ERROR, "event_parse_failed", error=str(exc))
        raise

    s3_path = f"s3://{bucket}/{key}"
    log(logging.INFO, "s3_event_parsed", bucket=bucket, key=key)

    # --- Secrets --------------------------------------------------------------
    # Only need the DB password — Redis invalidation is skipped in this Lambda
    # (no route to Upstash from the VPC private subnet).
    db_secret_arn = os.environ["DB_SECRET_ARN"]

    log(logging.INFO, "fetching_secrets")
    db_password = _get_secret(db_secret_arn)

    # --- Engine + schema (cold-start only) ------------------------------------
    if _engine is None:
        log(logging.INFO, "engine_cold_start")
        _engine = _build_engine(db_password)

    _ensure_db_initialised(_engine)

    # --- Read S3 object -------------------------------------------------------
    log(logging.INFO, "s3_read_start", key=key)
    try:
        response = _s3_client.get_object(Bucket=bucket, Key=key)
        raw_bytes = response["Body"].read()
    except ClientError as exc:
        log(logging.ERROR, "s3_read_failed", key=key, error=str(exc))
        raise

    # --- Validate payload -----------------------------------------------------
    try:
        payload = S3Payload.model_validate_json(raw_bytes)
    except Exception as exc:
        log(logging.ERROR, "payload_validation_failed", s3_path=s3_path, error=str(exc))
        raise

    log(logging.INFO, "payload_validated", record_count=payload.record_count)

    # --- Filter to state-level records ----------------------------------------
    transform_records: list[TransformRecord] = []
    skipped = 0
    for rec in payload.records:
        tr = TransformRecord.from_eia_record(rec)
        if tr is None:
            skipped += 1
        else:
            transform_records.append(tr)

    log(logging.INFO, "records_filtered", kept=len(transform_records), skipped=skipped)

    # --- Aggregate ------------------------------------------------------------
    weekly_rows = build_weekly(transform_records)
    monthly_rows = build_monthly(transform_records)
    yearly_rows = build_yearly(transform_records)

    log(logging.INFO, "aggregation_complete",
        weekly=len(weekly_rows), monthly=len(monthly_rows), yearly=len(yearly_rows))

    # --- Upsert + ingest_log (single transaction) ----------------------------
    log(logging.INFO, "db_upsert_start")
    try:
        with _engine.begin() as conn:
            w = _upsert_weekly(conn, weekly_rows)
            m = _upsert_monthly(conn, monthly_rows)
            y = _upsert_yearly(conn, yearly_rows)
            _write_ingest_log(conn, status="success",
                              records_fetched=len(transform_records), s3_path=s3_path)
    except Exception as exc:
        log(logging.ERROR, "db_upsert_failed", s3_path=s3_path, error=str(exc))
        # Log the failure in a fresh connection (the failed txn already rolled back)
        try:
            with _engine.begin() as conn:
                _write_ingest_log(conn, status="error", records_fetched=None,
                                  s3_path=s3_path, error_message=str(exc)[:1000])
        except Exception:
            log(logging.WARNING, "ingest_log_error_write_failed")
        raise

    log(logging.INFO, "db_upsert_complete", weekly=w, monthly=m, yearly=y)

    # --- Redis invalidation (skipped in transform Lambda) ---------------------
    # The transform Lambda runs in a private VPC subnet with no NAT gateway and
    # no route to the internet on port 6379. Upstash Redis is external and
    # unreachable from here. Any attempt to connect hangs for 70s+ (silent TCP
    # drop) before the OS-level retransmit timer fires, burning most of the
    # Lambda timeout.
    #
    # Resolution: skip invalidation here entirely. The Redis TTL (3600s) handles
    # staleness — prices update weekly, so a 1-hour stale cache window is fine.
    # The API Lambda (Phase 4) runs outside the VPC and can reach Upstash; cache
    # invalidation can be wired there on write if needed.
    log(logging.INFO, "redis_invalidation_skipped",
        reason="transform Lambda has no route to Upstash from VPC private subnet — TTL handles staleness")
    deleted_keys = 0

    result = {
        "statusCode": 200,
        "s3_path": s3_path,
        "records_transformed": len(transform_records),
        "weekly_upserted": w,
        "monthly_upserted": m,
        "yearly_upserted": y,
        "redis_keys_deleted": deleted_keys,
    }
    log(logging.INFO, "transform_complete", **result)
    return result
