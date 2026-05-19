"""
Pydantic v2 response models for the gas price API.

All response models are read-only (frozen=True) since they are only ever
serialised outwards — never mutated after construction.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class PricePoint(BaseModel):
    """Single data point in a price time series."""

    model_config = ConfigDict(frozen=True)

    date: str        # ISO string: YYYY-MM-DD (weekly), YYYY-MM (monthly), YYYY (yearly)
    avg_price: float


class PriceResponse(BaseModel):
    """Response for GET /v1/prices/{state}."""

    state: str
    period: str      # weekly | monthly | yearly
    grade: str
    data: list[PricePoint]
    source: str = "state"          # "state" = individual EIA series, "region" = PADD fallback
    region_name: Optional[str] = None  # e.g. "Midwest (PADD 2)" when source=="region"


class LatestPrice(BaseModel):
    """Single state entry in the latest-prices snapshot."""

    state: str
    avg_price: float
    week_start: str  # ISO date string YYYY-MM-DD
    source: str = "state"  # "state" | "region"


class LatestPricesResponse(BaseModel):
    """Response for GET /v1/prices/latest."""

    week_start: str  # most recent week_start across all states
    data: list[LatestPrice]


class NationalResponse(BaseModel):
    """Response for GET /v1/prices/national."""

    period: str
    grade: str
    data: list[PricePoint]


class CompareResponse(BaseModel):
    """Response for GET /v1/prices/compare."""

    period: str
    grade: str
    states: dict[str, list[PricePoint]]  # state abbreviation → time series


class StateInfo(BaseModel):
    """Single entry in the states list."""

    model_config = ConfigDict(frozen=True)

    name: str           # e.g. "California"
    abbreviation: str   # e.g. "CA"
    eia_code: str       # e.g. "SCA"


class StatesResponse(BaseModel):
    """Response for GET /v1/states."""

    data: list[StateInfo]


class HealthResponse(BaseModel):
    """Response for GET /v1/health — not cached."""

    status: str                     # healthy | degraded | unhealthy
    db_connected: bool
    cache_connected: bool
    last_ingest_at: Optional[str]   # ISO timestamp of most recent ingest_log row
    last_ingest_status: Optional[str]
