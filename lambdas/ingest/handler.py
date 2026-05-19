"""
Lambda entry point for the EIA gas price ingest function.

Normal mode (EventBridge weekly cron):
  1. Retrieve EIA API key from Secrets Manager.
  2. Fetch latest weekly prices from EIA API (with retry).
  3. Validate records with Pydantic v2.
  4. Write raw JSON to S3 at raw/YYYY/MM/DD/prices.json.
  5. Emit structured JSON logs at every step.
  6. Re-raise on failure so Lambda marks the invocation failed → DLQ.

Backfill mode (manual one-time invoke):
  Triggered by passing {"backfill": true, "start_date": "YYYY-MM-DD"}
  and optionally "end_date": "YYYY-MM-DD" in the event payload.

  Pages through ALL EIA records in the date range, groups them by year,
  and writes one S3 file per year:
    raw/backfill/YYYY/prices.json
  Each file triggers the transform Lambda via S3 event notification,
  so the full pipeline runs automatically.

  Designed to be invoked once per year from the CLI so each invocation
  stays well within the 60-second Lambda timeout:
    for year in $(seq 2000 2025); do
      aws lambda invoke \\
        --function-name gas-price-prod-ingest \\
        --invocation-type Event \\
        --payload "{\"backfill\":true,\"start_date\":\"${year}-01-01\",\"end_date\":\"${year}-12-31\"}" \\
        /dev/null
    done
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from eia_client import fetch_gas_prices, fetch_gas_prices_range
from models import EIAPriceRecord

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def log(level: int, event: str, **kwargs: Any) -> None:
    """Emit a structured JSON log line to CloudWatch."""
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


def _get_secret(secret_name: str) -> str:
    try:
        response = _secrets_client.get_secret_value(SecretId=secret_name)
    except ClientError as exc:
        log(logging.ERROR, "secrets_manager_error", secret=secret_name, error=str(exc))
        raise
    return response["SecretString"]


def _build_s3_key(now: datetime) -> str:
    return f"raw/{now.strftime('%Y/%m/%d')}/prices.json"


def _write_to_s3(bucket: str, key: str, records: list[EIAPriceRecord]) -> None:
    payload = json.dumps(
        {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "record_count": len(records),
            # mode="json" coerces Decimal to float for JSON serialisation
            "records": [r.model_dump(mode="json", by_alias=False) for r in records],
        },
        indent=2,
    )
    _s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=payload.encode("utf-8"),
        ContentType="application/json",
    )


# ---------------------------------------------------------------------------
# Backfill handler
# ---------------------------------------------------------------------------

def _handle_backfill(event: dict[str, Any], raw_bucket: str, eia_api_key: str) -> dict[str, Any]:
    """
    Fetch a date range from EIA and write one S3 file per calendar year.

    Each file lands under raw/backfill/YYYY/prices.json and triggers the
    transform Lambda automatically via S3 event notification.
    """
    start_date: str = event.get("start_date", "2000-01-01")
    end_date: str | None = event.get("end_date")

    log(logging.INFO, "backfill_start", start_date=start_date, end_date=end_date)

    # Collect records grouped by calendar year
    by_year: dict[int, list[EIAPriceRecord]] = defaultdict(list)
    total_fetched = 0

    for page_records, total in fetch_gas_prices_range(eia_api_key, start_date, end_date):
        for record in page_records:
            year = int(record.period[:4])
            by_year[year].append(record)
        total_fetched += len(page_records)
        log(logging.INFO, "backfill_page_fetched",
            fetched_so_far=total_fetched, api_total=total)

    log(logging.INFO, "backfill_fetch_complete",
        total_fetched=total_fetched, years=sorted(by_year.keys()))

    # Write one S3 file per year — each triggers the transform Lambda
    files_written: list[str] = []
    for year, records in sorted(by_year.items()):
        key = f"raw/backfill/{year}/prices.json"
        _write_to_s3(raw_bucket, key, records)
        files_written.append(key)
        log(logging.INFO, "backfill_year_written",
            year=year, record_count=len(records), s3_key=key)

    log(logging.INFO, "backfill_complete",
        files_written=len(files_written), total_records=total_fetched)

    return {
        "statusCode": 200,
        "mode": "backfill",
        "start_date": start_date,
        "end_date": end_date,
        "total_records_fetched": total_fetched,
        "files_written": len(files_written),
        "years": sorted(by_year.keys()),
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    raw_bucket = os.environ["RAW_BUCKET"]
    eia_secret_name = os.environ["EIA_SECRET_NAME"]

    # Fetch EIA API key (shared by both modes)
    log(logging.INFO, "fetching_eia_secret")
    eia_api_key = _get_secret(eia_secret_name)

    # ── Backfill mode ────────────────────────────────────────────────────────
    if event.get("backfill"):
        return _handle_backfill(event, raw_bucket, eia_api_key)

    # ── Normal weekly ingest mode ────────────────────────────────────────────
    log(logging.INFO, "ingest_start", trigger=event.get("source", "unknown"))

    # Fetch from EIA with retry
    log(logging.INFO, "eia_fetch_start")
    try:
        records = fetch_gas_prices(eia_api_key)
    except Exception as exc:
        log(logging.ERROR, "eia_fetch_failed", error=str(exc))
        raise

    log(logging.INFO, "eia_fetch_complete", record_count=len(records))

    # Write to S3
    now = datetime.now(timezone.utc)
    s3_key = _build_s3_key(now)

    log(logging.INFO, "s3_write_start", bucket=raw_bucket, key=s3_key)
    try:
        _write_to_s3(raw_bucket, s3_key, records)
    except ClientError as exc:
        log(logging.ERROR, "s3_write_failed", bucket=raw_bucket, key=s3_key, error=str(exc))
        raise

    s3_path = f"s3://{raw_bucket}/{s3_key}"
    log(logging.INFO, "ingest_complete", records=len(records), s3_path=s3_path)

    return {
        "statusCode": 200,
        "mode": "weekly",
        "records_fetched": len(records),
        "s3_path": s3_path,
    }
