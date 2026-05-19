"""
EIA API client with exponential backoff retry.

Fetches weekly regular gasoline prices for all US states and PADD regions from:
  https://api.eia.gov/v2/petroleum/pri/gnd/data/

Normal mode:  fetch_gas_prices()        – most recent ~60 records (one week)
Backfill mode: fetch_gas_prices_range() – paginate full date range, yields pages

Retry pattern: 3 attempts with 1s / 2s / 4s delays.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

import requests

from models import EIAResponse, EIAPriceRecord

logger = logging.getLogger(__name__)

EIA_BASE_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
DEFAULT_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3
# One record per area code per week. 60 covers all ~51 US state-level areas.
EIA_DEFAULT_LENGTH = 60
# Maximum records per page the EIA API allows.
EIA_PAGE_SIZE = 5000


def _build_params(api_key: str, length: int = EIA_DEFAULT_LENGTH) -> dict[str, Any]:
    return {
        "api_key":              api_key,
        "frequency":            "weekly",
        "data[]":               "value",
        "facets[product][]":    "EPM0",  # regular gasoline
        "facets[process][]":    "PTE",   # retail price — required to get PADD region codes
        "sort[0][column]":      "period",
        "sort[0][direction]":   "desc",
        "offset":               0,
        "length":               length,
    }


def _fetch_raw(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """
    HTTP GET with exponential backoff.

    Retries on: Timeout, ConnectionError, HTTP 429, HTTP 5xx.
    Raises immediately on non-retryable 4xx errors.
    """
    last_exc: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)

            if resp.status_code not in (429,) and resp.status_code < 500:
                resp.raise_for_status()
                return resp.json()

            # Retryable HTTP error
            resp.raise_for_status()

        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            last_exc = exc

            if status not in (429,) and status < 500:
                logger.error(json.dumps({
                    "event": "eia_http_error_no_retry",
                    "status_code": status,
                    "attempt": attempt + 1,
                    "error": str(exc),
                }))
                raise

            sleep_seconds = 2 ** attempt
            logger.warning(json.dumps({
                "event": "eia_http_error_retrying",
                "status_code": status,
                "attempt": attempt + 1,
                "sleep_seconds": sleep_seconds,
            }))
            if attempt < MAX_RETRIES - 1:
                time.sleep(sleep_seconds)

        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            sleep_seconds = 2 ** attempt
            logger.warning(json.dumps({
                "event": "eia_connection_error_retrying",
                "attempt": attempt + 1,
                "sleep_seconds": sleep_seconds,
                "error": str(exc),
            }))
            if attempt < MAX_RETRIES - 1:
                time.sleep(sleep_seconds)

    raise RuntimeError(
        f"EIA API request failed after {MAX_RETRIES} attempts"
    ) from last_exc


def fetch_gas_prices(api_key: str) -> list[EIAPriceRecord]:
    """
    Fetch the most recent weekly regular gasoline prices for all US areas.

    Returns a list of validated EIAPriceRecord instances.
    Raises RuntimeError if all retries are exhausted.
    """
    params = _build_params(api_key)
    raw = _fetch_raw(EIA_BASE_URL, params)

    response_model = EIAResponse.model_validate(raw)

    logger.info(json.dumps({
        "event": "eia_fetch_success",
        "record_count": len(response_model.data),
    }))

    return response_model.data


def fetch_gas_prices_range(
    api_key: str,
    start_date: str,
    end_date: str | None = None,
) -> Iterator[tuple[list[EIAPriceRecord], int]]:
    """
    Paginate all EIA weekly gas price records within a date range.

    Yields (page_records, total) tuples where `total` is the full result count
    reported by the API. Callers can use this to log progress.

    Args:
        api_key:    EIA Open Data API key.
        start_date: ISO date string, e.g. "2000-01-01".
        end_date:   ISO date string (inclusive). Omit for up to today.
    """
    offset = 0
    total: int | None = None

    while True:
        params: dict[str, Any] = {
            "api_key":              api_key,
            "frequency":            "weekly",
            "data[]":               "value",
            "facets[product][]":    "EPM0",  # regular gasoline
            "facets[process][]":    "PTE",   # retail price — required to get PADD region codes
            "sort[0][column]":      "period",
            "sort[0][direction]":   "asc",
            "offset":               offset,
            "length":               EIA_PAGE_SIZE,
            "start":                start_date,
        }
        if end_date:
            params["end"] = end_date

        raw = _fetch_raw(EIA_BASE_URL, params)
        response = raw.get("response", {})
        page_data: list[dict] = response.get("data", [])

        if total is None:
            total = int(response.get("total", 0))

        if not page_data:
            break

        # Validate each record individually — skip any malformed rows
        records: list[EIAPriceRecord] = []
        for item in page_data:
            try:
                records.append(EIAPriceRecord.model_validate(item))
            except Exception as exc:
                logger.warning(json.dumps({
                    "event": "eia_record_validation_skipped",
                    "duoarea": item.get("duoarea"),
                    "period":  item.get("period"),
                    "error":   str(exc),
                }))

        yield records, total

        offset += len(page_data)
        if total and offset >= total:
            break
