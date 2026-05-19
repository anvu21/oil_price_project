"""
Price and state endpoints.

Route registration order matters — FastAPI matches routes in definition order.
Static paths (/latest, /national, /compare) must be registered BEFORE the
parametric path (/{state}) to prevent them being swallowed as state names.
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Query
from sqlalchemy import text

from cache import cache_get, cache_set, cache_ping
from db import get_db
from exceptions import DatabaseUnavailableError, InvalidPeriodError, StateNotFoundError
from models import (
    CompareResponse,
    HealthResponse,
    LatestPrice,
    LatestPricesResponse,
    NationalResponse,
    PricePoint,
    PriceResponse,
    StateInfo,
    StatesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_PERIODS = {"weekly", "monthly", "yearly"}
VALID_GRADES  = {"regular", "midgrade", "premium", "diesel"}

# ---------------------------------------------------------------------------
# PADD region mappings
# EIA only publishes individual weekly retail prices for 9 states:
# CA, CO, FL, MA, MN, NY, OH, TX, WA.
# All other states fall back to their PADD (Petroleum Administration for
# Defense Districts) regional average.
# ---------------------------------------------------------------------------

# Maps state abbreviation → PADD region code stored in the DB.
# States in STATES_WITH_DIRECT_DATA are NOT in this map — they use their own series.
STATE_TO_PADD: dict[str, str] = {
    # PADD 1A — New England
    "CT": "R1X", "ME": "R1X", "NH": "R1X", "RI": "R1X", "VT": "R1X",
    # PADD 1B — Central Atlantic
    "DC": "R1Y", "DE": "R1Y", "MD": "R1Y", "NJ": "R1Y", "PA": "R1Y",
    # PADD 1C — Lower Atlantic
    "GA": "R1Z", "NC": "R1Z", "SC": "R1Z", "VA": "R1Z", "WV": "R1Z",
    # PADD 2 — Midwest
    "IL": "R20", "IN": "R20", "IA": "R20", "KS": "R20", "KY": "R20",
    "MI": "R20", "MO": "R20", "NE": "R20", "ND": "R20", "OK": "R20",
    "SD": "R20", "TN": "R20", "WI": "R20",
    # PADD 3 — Gulf Coast
    "AL": "R30", "AR": "R30", "LA": "R30", "MS": "R30", "NM": "R30",
    # PADD 4 — Rocky Mountain
    "ID": "R40", "MT": "R40", "UT": "R40", "WY": "R40",
    # PADD 5 — West Coast (AK, AZ, HI, NV, OR — CA & WA have individual data)
    "AK": "R50", "AZ": "R50", "HI": "R50", "NV": "R50", "OR": "R50",
}

PADD_NAMES: dict[str, str] = {
    "R1X": "New England (PADD 1A)",
    "R1Y": "Central Atlantic (PADD 1B)",
    "R1Z": "Lower Atlantic (PADD 1C)",
    "R20": "Midwest (PADD 2)",
    "R30": "Gulf Coast (PADD 3)",
    "R40": "Rocky Mountain (PADD 4)",
    "R50": "West Coast (PADD 5)",
}

# ---------------------------------------------------------------------------
# Static states data — name, abbreviation, EIA area code (S + abbreviation)
# Cached for 24 hours at the API layer since this data never changes.
# ---------------------------------------------------------------------------

_STATES: list[StateInfo] = [
    StateInfo(name="Alabama",              abbreviation="AL", eia_code="SAL"),
    StateInfo(name="Alaska",               abbreviation="AK", eia_code="SAK"),
    StateInfo(name="Arizona",              abbreviation="AZ", eia_code="SAZ"),
    StateInfo(name="Arkansas",             abbreviation="AR", eia_code="SAR"),
    StateInfo(name="California",           abbreviation="CA", eia_code="SCA"),
    StateInfo(name="Colorado",             abbreviation="CO", eia_code="SCO"),
    StateInfo(name="Connecticut",          abbreviation="CT", eia_code="SCT"),
    StateInfo(name="Delaware",             abbreviation="DE", eia_code="SDE"),
    StateInfo(name="District of Columbia", abbreviation="DC", eia_code="SDC"),
    StateInfo(name="Florida",              abbreviation="FL", eia_code="SFL"),
    StateInfo(name="Georgia",              abbreviation="GA", eia_code="SGA"),
    StateInfo(name="Hawaii",               abbreviation="HI", eia_code="SHI"),
    StateInfo(name="Idaho",                abbreviation="ID", eia_code="SID"),
    StateInfo(name="Illinois",             abbreviation="IL", eia_code="SIL"),
    StateInfo(name="Indiana",              abbreviation="IN", eia_code="SIN"),
    StateInfo(name="Iowa",                 abbreviation="IA", eia_code="SIA"),
    StateInfo(name="Kansas",               abbreviation="KS", eia_code="SKS"),
    StateInfo(name="Kentucky",             abbreviation="KY", eia_code="SKY"),
    StateInfo(name="Louisiana",            abbreviation="LA", eia_code="SLA"),
    StateInfo(name="Maine",                abbreviation="ME", eia_code="SME"),
    StateInfo(name="Maryland",             abbreviation="MD", eia_code="SMD"),
    StateInfo(name="Massachusetts",        abbreviation="MA", eia_code="SMA"),
    StateInfo(name="Michigan",             abbreviation="MI", eia_code="SMI"),
    StateInfo(name="Minnesota",            abbreviation="MN", eia_code="SMN"),
    StateInfo(name="Mississippi",          abbreviation="MS", eia_code="SMS"),
    StateInfo(name="Missouri",             abbreviation="MO", eia_code="SMO"),
    StateInfo(name="Montana",              abbreviation="MT", eia_code="SMT"),
    StateInfo(name="Nebraska",             abbreviation="NE", eia_code="SNE"),
    StateInfo(name="Nevada",               abbreviation="NV", eia_code="SNV"),
    StateInfo(name="New Hampshire",        abbreviation="NH", eia_code="SNH"),
    StateInfo(name="New Jersey",           abbreviation="NJ", eia_code="SNJ"),
    StateInfo(name="New Mexico",           abbreviation="NM", eia_code="SNM"),
    StateInfo(name="New York",             abbreviation="NY", eia_code="SNY"),
    StateInfo(name="North Carolina",       abbreviation="NC", eia_code="SNC"),
    StateInfo(name="North Dakota",         abbreviation="ND", eia_code="SND"),
    StateInfo(name="Ohio",                 abbreviation="OH", eia_code="SOH"),
    StateInfo(name="Oklahoma",             abbreviation="OK", eia_code="SOK"),
    StateInfo(name="Oregon",               abbreviation="OR", eia_code="SOR"),
    StateInfo(name="Pennsylvania",         abbreviation="PA", eia_code="SPA"),
    StateInfo(name="Rhode Island",         abbreviation="RI", eia_code="SRI"),
    StateInfo(name="South Carolina",       abbreviation="SC", eia_code="SSC"),
    StateInfo(name="South Dakota",         abbreviation="SD", eia_code="SSD"),
    StateInfo(name="Tennessee",            abbreviation="TN", eia_code="STN"),
    StateInfo(name="Texas",                abbreviation="TX", eia_code="STX"),
    StateInfo(name="Utah",                 abbreviation="UT", eia_code="SUT"),
    StateInfo(name="Vermont",              abbreviation="VT", eia_code="SVT"),
    StateInfo(name="Virginia",             abbreviation="VA", eia_code="SVA"),
    StateInfo(name="Washington",           abbreviation="WA", eia_code="SWA"),
    StateInfo(name="West Virginia",        abbreviation="WV", eia_code="SWV"),
    StateInfo(name="Wisconsin",            abbreviation="WI", eia_code="SWI"),
    StateInfo(name="Wyoming",              abbreviation="WY", eia_code="SWY"),
]

_VALID_STATES = {s.abbreviation.upper() for s in _STATES}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_period(period: str) -> None:
    if period not in VALID_PERIODS:
        raise InvalidPeriodError(
            f"period must be one of: {', '.join(sorted(VALID_PERIODS))}"
        )


def _validate_grade(grade: str) -> None:
    if grade not in VALID_GRADES:
        raise InvalidPeriodError(
            f"grade must be one of: {', '.join(sorted(VALID_GRADES))}"
        )


def _validate_state(state: str) -> str:
    """Normalise to uppercase and validate against the known state list."""
    s = state.upper()
    if s not in _VALID_STATES:
        raise StateNotFoundError(f"Unknown state abbreviation: {state!r}")
    return s


# ---------------------------------------------------------------------------
# GET /v1/prices/latest  — registered before /{state} to avoid route conflict
# ---------------------------------------------------------------------------

@router.get("/prices/latest", response_model=LatestPricesResponse)
def get_latest_prices(grade: str = "regular"):
    """Most recent week's price for every state. Powers the choropleth map.

    States with individual EIA data (CA, CO, FL, MA, MN, NY, OH, TX, WA) use
    their own series.  All other states fall back to their PADD regional average
    so that the choropleth map is fully populated.
    """
    _validate_grade(grade)

    cache_key = f"prices:latest:{grade}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        with get_db() as db:
            # Single query: pulls latest row for every state code AND every PADD code.
            rows = db.execute(text("""
                SELECT DISTINCT ON (state) state, week_start, avg_price
                FROM prices_weekly
                WHERE grade = :grade
                ORDER BY state, week_start DESC
            """), {"grade": grade}).fetchall()
    except Exception as exc:
        raise DatabaseUnavailableError() from exc

    if not rows:
        result = {"week_start": "", "data": []}
    else:
        # Build a lookup keyed by state abbreviation or PADD code
        by_code: dict = {r.state: r for r in rows}

        # max_week is the most recent individual-state week (2-char codes only)
        state_weeks = [r.week_start for r in rows if len(r.state) == 2]
        max_week = str(max(state_weeks)) if state_weeks else str(max(r.week_start for r in rows))

        data = []
        for s in _STATES:
            abbr = s.abbreviation
            if abbr in by_code:
                # Individual state data exists
                r = by_code[abbr]
                data.append({
                    "state":      abbr,
                    "avg_price":  float(r.avg_price),
                    "week_start": str(r.week_start),
                    "source":     "state",
                })
            else:
                # Fall back to PADD regional data
                padd_code = STATE_TO_PADD.get(abbr)
                if padd_code and padd_code in by_code:
                    r = by_code[padd_code]
                    data.append({
                        "state":      abbr,
                        "avg_price":  float(r.avg_price),
                        "week_start": str(r.week_start),
                        "source":     "region",
                    })
                # else: no data at all — omit; map will show gray

        result = {"week_start": max_week, "data": data}

    cache_set(cache_key, result, ttl=3600)
    return result


# ---------------------------------------------------------------------------
# GET /v1/prices/national
# ---------------------------------------------------------------------------

@router.get("/prices/national", response_model=NationalResponse)
def get_national_prices(
    period:    str = "weekly",
    grade:     str = "regular",
    from_date: Annotated[Optional[str], Query(alias="from")] = None,
    to_date:   Annotated[Optional[str], Query(alias="to")]   = None,
):
    """National average (mean across all states) for the requested period."""
    _validate_period(period)
    _validate_grade(grade)

    cache_key = f"prices:national:{period}:{grade}:{from_date}:{to_date}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    try:
        with get_db() as db:
            data = _query_national(db, period, grade, from_date, to_date)
    except (InvalidPeriodError, StateNotFoundError):
        raise
    except Exception as exc:
        raise DatabaseUnavailableError() from exc

    result = {"period": period, "grade": grade, "data": data}
    cache_set(cache_key, result, ttl=3600)
    return result


def _query_national(db, period: str, grade: str, from_date, to_date) -> list:
    # LENGTH(state) = 2 excludes PADD region codes (R1X, R20, etc.) so that
    # the national average is computed only from individual-state rows.
    if period == "weekly":
        where, params = "WHERE LENGTH(state) = 2 AND grade = :grade", {"grade": grade}
        if from_date:
            where += " AND week_start >= :from_date"
            params["from_date"] = from_date
        if to_date:
            where += " AND week_start <= :to_date"
            params["to_date"] = to_date
        rows = db.execute(text(f"""
            SELECT week_start AS date, AVG(avg_price) AS avg_price
            FROM prices_weekly {where}
            GROUP BY week_start ORDER BY week_start
        """), params).fetchall()
        return [{"date": str(r.date), "avg_price": round(float(r.avg_price), 3)} for r in rows]

    elif period == "monthly":
        where, params = "WHERE LENGTH(state) = 2 AND grade = :grade", {"grade": grade}
        if from_date:
            where += " AND year_month >= :from_date"
            # Accept YYYY-MM or YYYY-MM-DD; normalise to first of month
            params["from_date"] = (from_date + "-01")[:10]
        if to_date:
            where += " AND year_month <= :to_date"
            params["to_date"] = (to_date + "-01")[:10]
        rows = db.execute(text(f"""
            SELECT year_month AS date, AVG(avg_price) AS avg_price
            FROM prices_monthly {where}
            GROUP BY year_month ORDER BY year_month
        """), params).fetchall()
        # Return YYYY-MM format for monthly dates
        return [{"date": str(r.date)[:7], "avg_price": round(float(r.avg_price), 3)} for r in rows]

    else:  # yearly
        where, params = "WHERE LENGTH(state) = 2 AND grade = :grade", {"grade": grade}
        if from_date:
            where += " AND year >= :from_year"
            params["from_year"] = int(str(from_date)[:4])
        if to_date:
            where += " AND year <= :to_year"
            params["to_year"] = int(str(to_date)[:4])
        rows = db.execute(text(f"""
            SELECT year AS date, AVG(avg_price) AS avg_price
            FROM prices_yearly {where}
            GROUP BY year ORDER BY year
        """), params).fetchall()
        return [{"date": str(r.date), "avg_price": round(float(r.avg_price), 3)} for r in rows]


# ---------------------------------------------------------------------------
# GET /v1/prices/compare
# ---------------------------------------------------------------------------

@router.get("/prices/compare", response_model=CompareResponse)
def get_compare_prices(
    states:    str = Query(..., description="Comma-separated state abbreviations, e.g. CA,TX,FL"),
    period:    str = "weekly",
    grade:     str = "regular",
    from_date: Annotated[Optional[str], Query(alias="from")] = None,
    to_date:   Annotated[Optional[str], Query(alias="to")]   = None,
):
    """Side-by-side price series for multiple states."""
    _validate_period(period)
    _validate_grade(grade)

    state_list = [_validate_state(s.strip()) for s in states.split(",") if s.strip()]
    if not state_list:
        raise StateNotFoundError("states parameter must contain at least one abbreviation")

    sorted_key  = ",".join(sorted(state_list))
    cache_key   = f"prices:compare:{sorted_key}:{period}:{grade}:{from_date}:{to_date}"
    cached      = cache_get(cache_key)
    if cached:
        return cached

    try:
        with get_db() as db:
            state_data = _query_compare(db, state_list, period, grade, from_date, to_date)
    except (InvalidPeriodError, StateNotFoundError):
        raise
    except Exception as exc:
        raise DatabaseUnavailableError() from exc

    result = {"period": period, "grade": grade, "states": state_data}
    cache_set(cache_key, result, ttl=3600)
    return result


def _query_compare(db, state_list: list, period: str, grade: str, from_date, to_date) -> dict:
    """Return {state: [PricePoint]} for all requested states."""
    result: dict[str, list] = {s: [] for s in state_list}

    if period == "weekly":
        where  = "WHERE state = ANY(:states) AND grade = :grade"
        params: dict = {"states": state_list, "grade": grade}
        if from_date:
            where += " AND week_start >= :from_date"
            params["from_date"] = from_date
        if to_date:
            where += " AND week_start <= :to_date"
            params["to_date"] = to_date
        rows = db.execute(text(f"""
            SELECT state, week_start AS date, avg_price
            FROM prices_weekly {where} ORDER BY state, week_start
        """), params).fetchall()
        for r in rows:
            result[r.state].append({"date": str(r.date), "avg_price": float(r.avg_price)})

    elif period == "monthly":
        where  = "WHERE state = ANY(:states) AND grade = :grade"
        params = {"states": state_list, "grade": grade}
        if from_date:
            where += " AND year_month >= :from_date"
            params["from_date"] = (from_date + "-01")[:10]
        if to_date:
            where += " AND year_month <= :to_date"
            params["to_date"] = (to_date + "-01")[:10]
        rows = db.execute(text(f"""
            SELECT state, year_month AS date, avg_price
            FROM prices_monthly {where} ORDER BY state, year_month
        """), params).fetchall()
        for r in rows:
            result[r.state].append({"date": str(r.date)[:7], "avg_price": float(r.avg_price)})

    else:  # yearly
        where  = "WHERE state = ANY(:states) AND grade = :grade"
        params = {"states": state_list, "grade": grade}
        if from_date:
            where += " AND year >= :from_year"
            params["from_year"] = int(str(from_date)[:4])
        if to_date:
            where += " AND year <= :to_year"
            params["to_year"] = int(str(to_date)[:4])
        rows = db.execute(text(f"""
            SELECT state, year AS date, avg_price
            FROM prices_yearly {where} ORDER BY state, year
        """), params).fetchall()
        for r in rows:
            result[r.state].append({"date": str(r.date), "avg_price": float(r.avg_price)})

    return result


# ---------------------------------------------------------------------------
# GET /v1/prices/{state}  — parametric, must come AFTER all static /prices/* routes
# ---------------------------------------------------------------------------

@router.get("/prices/{state}", response_model=PriceResponse)
def get_state_prices(
    state:     str,
    period:    str = "weekly",
    grade:     str = "regular",
    from_date: Annotated[Optional[str], Query(alias="from")] = None,
    to_date:   Annotated[Optional[str], Query(alias="to")]   = None,
):
    """Price time series for a single state.

    If the EIA does not publish individual data for the requested state, the
    response falls back to the state's PADD regional average.  The response
    includes ``source`` ("state" | "region") and, when regional, ``region_name``
    (e.g. "Midwest (PADD 2)").
    """
    state = _validate_state(state)
    _validate_period(period)
    _validate_grade(grade)

    cache_key = f"prices:{state}:{period}:{grade}:{from_date}:{to_date}"
    cached    = cache_get(cache_key)
    if cached:
        return cached

    source      = "state"
    region_name = None

    try:
        with get_db() as db:
            data = _query_state(db, state, period, grade, from_date, to_date)

            # No individual series — try PADD regional fallback
            if not data:
                padd_code = STATE_TO_PADD.get(state)
                if padd_code:
                    data = _query_state(db, padd_code, period, grade, from_date, to_date)
                    if data:
                        source      = "region"
                        region_name = PADD_NAMES.get(padd_code)
    except (InvalidPeriodError, StateNotFoundError):
        raise
    except Exception as exc:
        raise DatabaseUnavailableError() from exc

    if not data:
        raise StateNotFoundError(
            f"No {period} data found for state '{state}' with grade='{grade}'"
        )

    result = {
        "state":       state,
        "period":      period,
        "grade":       grade,
        "data":        data,
        "source":      source,
        "region_name": region_name,
    }
    cache_set(cache_key, result, ttl=3600)
    return result


def _query_state(db, state: str, period: str, grade: str, from_date, to_date) -> list:
    if period == "weekly":
        where  = "WHERE state = :state AND grade = :grade"
        params: dict = {"state": state, "grade": grade}
        if from_date:
            where += " AND week_start >= :from_date"
            params["from_date"] = from_date
        if to_date:
            where += " AND week_start <= :to_date"
            params["to_date"] = to_date
        rows = db.execute(text(f"""
            SELECT week_start AS date, avg_price
            FROM prices_weekly {where} ORDER BY week_start
        """), params).fetchall()
        return [{"date": str(r.date), "avg_price": float(r.avg_price)} for r in rows]

    elif period == "monthly":
        where  = "WHERE state = :state AND grade = :grade"
        params = {"state": state, "grade": grade}
        if from_date:
            where += " AND year_month >= :from_date"
            params["from_date"] = (from_date + "-01")[:10]
        if to_date:
            where += " AND year_month <= :to_date"
            params["to_date"] = (to_date + "-01")[:10]
        rows = db.execute(text(f"""
            SELECT year_month AS date, avg_price
            FROM prices_monthly {where} ORDER BY year_month
        """), params).fetchall()
        return [{"date": str(r.date)[:7], "avg_price": float(r.avg_price)} for r in rows]

    else:  # yearly
        where  = "WHERE state = :state AND grade = :grade"
        params = {"state": state, "grade": grade}
        if from_date:
            where += " AND year >= :from_year"
            params["from_year"] = int(str(from_date)[:4])
        if to_date:
            where += " AND year <= :to_year"
            params["to_year"] = int(str(to_date)[:4])
        rows = db.execute(text(f"""
            SELECT year AS date, avg_price
            FROM prices_yearly {where} ORDER BY year
        """), params).fetchall()
        return [{"date": str(r.date), "avg_price": float(r.avg_price)} for r in rows]


# ---------------------------------------------------------------------------
# GET /v1/states
# ---------------------------------------------------------------------------

@router.get("/states", response_model=StatesResponse)
def get_states():
    """List all 50 states + DC with their EIA area codes. Cached for 24 hours."""
    cache_key = "states:all"
    cached    = cache_get(cache_key)
    if cached:
        return cached

    result = {"data": [s.model_dump() for s in _STATES]}
    cache_set(cache_key, result, ttl=86400)
    return result


# ---------------------------------------------------------------------------
# GET /v1/health  — not cached; used as a CloudWatch alarm source
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
def health_check():
    """
    Returns connectivity status for the DB and cache, plus last ingest metadata.
    Always queries live — never served from cache.
    """
    import os
    import socket as _socket

    # --- Raw TCP connectivity test (diagnostic) ---
    # Tests basic network reachability before psycopg2/SSL layer.
    # result=0 means TCP connect succeeded; non-zero or exception means blocked.
    db_host = os.environ.get("DB_HOST", "")
    db_port = int(os.environ.get("DB_PORT", "5432"))
    try:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.settimeout(5)
        tcp_result = sock.connect_ex((db_host, db_port))
        sock.close()
        logger.info("tcp_test host=%s port=%d result=%d (0=ok)", db_host, db_port, tcp_result)
    except Exception as exc:
        logger.error("tcp_test failed: %s", exc)
        tcp_result = -1

    # --- DB check ---
    db_ok              = False
    last_ingest_at     = None
    last_ingest_status = None
    try:
        with get_db() as db:
            db.execute(text("SELECT 1"))
            db_ok = True
            row = db.execute(text("""
                SELECT run_at, status
                FROM ingest_log
                ORDER BY run_at DESC LIMIT 1
            """)).fetchone()
            if row:
                last_ingest_at     = str(row.run_at)
                last_ingest_status = row.status
    except Exception as exc:
        logger.error("Health check DB query failed: %s", exc)
        db_ok = False

    # --- Cache check ---
    cache_ok = cache_ping()

    # --- Status roll-up ---
    if db_ok and cache_ok:
        status = "healthy"
    elif db_ok:
        status = "degraded"    # Redis down but API still serves from RDS
    else:
        status = "unhealthy"

    return {
        "status":              status,
        "db_connected":        db_ok,
        "cache_connected":     cache_ok,
        "last_ingest_at":      last_ingest_at,
        "last_ingest_status":  last_ingest_status,
    }
