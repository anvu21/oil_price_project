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


class TransformRecord(BaseModel):
    """
    Normalised record after filtering out non-state duoarea codes.

    EIA state codes: 'SCA' → state='CA', 'STX' → state='TX', etc.
    Region codes like 'R10', 'R20', and national codes like 'U' are skipped.
    """

    model_config = ConfigDict(frozen=True)

    state: str
    week_start: date
    avg_price: Decimal
    grade: str = "regular"

    @classmethod
    def from_eia_record(cls, record: EIAPriceRecord) -> "TransformRecord | None":
        """
        Return a TransformRecord or None if duoarea is not a state-level code.

        State codes are exactly 3 characters starting with 'S' followed by a
        2-letter abbreviation. Any other format is a region or national aggregate.
        """
        code = record.duoarea
        if len(code) != 3 or code[0] != "S":
            return None
        state = code[1:]  # strip leading 'S' → 'CA', 'TX', etc.
        return cls(
            state=state,
            week_start=date.fromisoformat(record.period),
            avg_price=record.value,
        )
