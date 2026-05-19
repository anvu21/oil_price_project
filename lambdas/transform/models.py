"""
Pydantic v2 models for the transform Lambda.

EIAPriceRecord is a self-contained copy from the ingest Lambda — each Lambda
ZIP is independent and cannot import across packages.

S3Payload validates the full JSON object written by the ingest Lambda.
TransformRecord is a derived model with normalised fields (state code, parsed
date) used by the aggregator.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EIAPriceRecord(BaseModel):
    """Single weekly price record as returned by the EIA API."""

    model_config = ConfigDict(populate_by_name=True, frozen=True)

    period: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    duoarea: str = Field(..., min_length=2, max_length=5)
    area_name: str | None = Field(default=None, alias="areaName")
    product: str
    value: Decimal = Field(..., gt=Decimal("0"), lt=Decimal("20"))
    units: str = Field(default="$/gal")

    @field_validator("value", mode="before")
    @classmethod
    def parse_price_string(cls, v: Any) -> Decimal:
        if isinstance(v, str):
            v = v.strip()
            if not v or v.lower() in ("null", "none", ""):
                raise ValueError("price value is null or empty")
        try:
            return Decimal(str(v))
        except Exception as exc:
            raise ValueError(f"cannot parse price value: {v!r}") from exc

    @field_validator("period", mode="after")
    @classmethod
    def validate_period_is_real_date(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"period is not a valid date: {v!r}") from exc
        return v


class S3Payload(BaseModel):
    """Top-level JSON structure written by the ingest Lambda to S3."""

    model_config = ConfigDict(populate_by_name=True)

    fetched_at: str
    record_count: int
    records: list[EIAPriceRecord]


# PADD region codes published by EIA for weekly retail gasoline prices.
# Used as fallback data for the 42 states that lack individual EIA reporting.
#   R1X = PADD 1A  New England      (CT, ME, NH, RI, VT)
#   R1Y = PADD 1B  Central Atlantic (DC, DE, MD, NJ, PA)
#   R1Z = PADD 1C  Lower Atlantic   (GA, NC, SC, VA, WV)
#   R20 = PADD 2   Midwest          (IL, IN, IA, KS, KY, MI, MO, NE, ND, OK, SD, TN, WI)
#   R30 = PADD 3   Gulf Coast       (AL, AR, LA, MS, NM)
#   R40 = PADD 4   Rocky Mountain   (ID, MT, UT, WY)
#   R50 = PADD 5   West Coast excl. CA & WA (AK, AZ, HI, NV, OR)
_VALID_PADDS: frozenset[str] = frozenset({"R1X", "R1Y", "R1Z", "R20", "R30", "R40", "R50"})


class TransformRecord(BaseModel):
    """
    Normalised record after filtering out non-state / non-PADD duoarea codes.

    EIA state codes:  'SCA' → state='CA', 'STX' → state='TX', etc.
    EIA PADD codes:   'R1X', 'R20', … → stored as-is (3-char key, VARCHAR(10))
    Everything else:  national 'U', metro areas, aggregated 'R10' → skipped.
    """

    model_config = ConfigDict(frozen=True)

    state: str
    week_start: date
    avg_price: Decimal
    grade: str = "regular"

    @classmethod
    def from_eia_record(cls, record: EIAPriceRecord) -> "TransformRecord | None":
        """
        Return a TransformRecord or None if duoarea is not storable.

        Accepts:
          - State codes  (len==3, starts with 'S') → strip 'S' → 2-char state abbr
          - PADD codes   (R1X, R1Y, R1Z, R20, R30, R40, R50) → kept as-is
        Skips everything else (national, metro, broad regional like R10).
        """
        code = record.duoarea

        # Individual state code: e.g. 'SCA' → 'CA'
        if len(code) == 3 and code[0] == "S":
            return cls(
                state=code[1:],
                week_start=date.fromisoformat(record.period),
                avg_price=record.value,
            )

        # PADD region code: e.g. 'R1X', 'R20' — kept verbatim
        if code in _VALID_PADDS:
            return cls(
                state=code,
                week_start=date.fromisoformat(record.period),
                avg_price=record.value,
            )

        return None
