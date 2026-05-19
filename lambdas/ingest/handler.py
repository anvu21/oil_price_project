"""
Lambda entry point for the EIA gas price ingest function.

Triggered by EventBridge: cron(0 14 ? * MON *) — Monday 14:00 UTC,
after EIA publishes the weekly update.

Flow:
  1. Retrieve EIA API key from Secrets Manager.
  2. Fetch latest weekly prices from EIA API (with retry).
  3. Validate records with Pydantic v2.
  4. Write raw JSON to S3 at raw/YYYY/MM/DD/prices.json.
  5. Emit structured JSON logs at every step.
  6. Re-raise on failure so Lambda marks the invocation failed → DLQ.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from eia_client import fetch_gas_prices
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
# Handler
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    log(logging.INFO, "ingest_start", trigger=event.get("source", "unknown"))

    raw_bucket = os.environ["RAW_BUCKET"]
    eia_secret_name = os.environ["EIA_SECRET_NAME"]

    # 1. EIA API key from Secrets Manager
    log(logging.INFO, "fetching_eia_secret")
    eia_api_key = _get_secret(eia_secret_name)

    # 2. Fetch from EIA with retry
    log(logging.INFO, "eia_fetch_start")
    try:
        records = fetch_gas_prices(eia_api_key)
    except Exception as exc:
        log(logging.ERROR, "eia_fetch_failed", error=str(exc))
        raise

    log(logging.INFO, "eia_fetch_complete", record_count=len(records))

    # 3. Write to S3
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
        "records_fetched": len(records),
        "s3_path": s3_path,
    }
