"""
Pydantic v2 models for EIA API responses.

EIA response shape (relevant subset):
{
  "response": {
    "data": [
      {
        "period":   "2025-03-17",   # ISO week-start date string
        "duoarea":  "SCA",          # EIA area code (S + state abbreviation)
        "areaName": "California",
        "product":  "EPM0",         # regular gasoline
        "value":    "3.845",        # price per gallon as a string
        "units":    "$/gal"
      }
    ]
  }
}
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EIAPriceRecord(BaseModel):
    """A single weekly price record returned by the EIA API."""

    model_config = ConfigDict(
        populate_by_name=True,
        frozen=True,
    )

    period: str = Field(
        ...,
        description="ISO week-start date (YYYY-MM-DD).",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    duoarea: str = Field(
        ...,
        description="EIA area code, e.g. 'SCA' for California.",
        min_length=2,
        max_length=5,
    )
    area_name: str | None = Field(
        default=None,
        alias="areaName",
        description="Human-readable area name, e.g. 'California'.",
    )
    product: str = Field(
        ...,
        description="EIA product code. EPM0 = regular gasoline.",
    )
    value: Decimal = Field(
        ...,
        description="Price per gallon in USD.",
        gt=Decimal("0"),
        lt=Decimal("20"),
    )
    units: str = Field(
        default="$/gal",
        description="Unit string returned by EIA API.",
    )

    @field_validator("value", mode="before")
    @classmethod
    def parse_price_string(cls, v: Any) -> Decimal:
        """EIA returns value as a string like '3.845'. Convert to Decimal."""
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
        """Reject period strings that are syntactically correct but not real dates."""
        from datetime import date

        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"period is not a valid date: {v!r}") from exc
        return v


class EIAResponse(BaseModel):
    """Top-level EIA API response envelope."""

    model_config = ConfigDict(populate_by_name=True)

    data: list[EIAPriceRecord] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def unwrap_response_envelope(cls, v: Any) -> Any:
        """
        EIA wraps its payload in {"response": {"data": [...]}}.
        Accept either the full envelope or the already-unwrapped inner dict.
        """
        if isinstance(v, dict) and "response" in v:
            return v["response"]
        return v
