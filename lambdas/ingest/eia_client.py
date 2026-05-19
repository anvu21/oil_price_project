"""
EIA API client with exponential backoff retry.

Fetches weekly regular gasoline prices for all US states from:
  https://api.eia.gov/v2/petroleum/pri/gnd/data/

Retry pattern: 3 attempts with 1s / 2s / 4s delays.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from models import EIAResponse, EIAPriceRecord

logger = logging.getLogger(__name__)

EIA_BASE_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
DEFAULT_TIMEOUT_SECONDS = 15
MAX_RETRIES = 3
# One record per area code per week. 60 covers all ~51 US state-level areas.
EIA_DEFAULT_LENGTH = 60


def _build_params(api_key: str, length: int = EIA_DEFAULT_LENGTH) -> dict[str, Any]:
    return {
        "api_key": api_key,
        "frequency": "weekly",
        "data[]": "value",
        "facets[product][]": "EPM0",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "offset": 0,
        "length": length,
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
