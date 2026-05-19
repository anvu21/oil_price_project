#!/usr/bin/env python3
"""
backfill.py — Fetch historical EIA weekly gas price data into the local (or prod) DB.

Calls the EIA Open Data API, filters to state-level records, upserts weekly
prices, then recomputes monthly and yearly rollups.

Usage:
    python scripts/backfill.py [--years N] [--api-key KEY]

    --years N     How many years of history to fetch (default: 3)
    --api-key KEY EIA API key (overrides EIA_API_KEY env var)

Environment variables (all have sensible local-dev defaults):
    EIA_API_KEY   EIA Open Data API key
    DB_HOST       default: localhost
    DB_PORT       default: 5432
    DB_NAME       default: gas_prices
    DB_USERNAME   default: gas_price_admin
    DB_PASSWORD   default: localpassword
"""

import argparse
import os
import sys
import time
from datetime import date, timedelta
from typing import Iterator

import psycopg2
import psycopg2.extras
import requests

# ---------------------------------------------------------------------------
# EIA API
# ---------------------------------------------------------------------------

EIA_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"
PAGE_SIZE = 5000  # max the EIA API allows per request

VALID_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","DC","FL","GA","HI","ID","IL",
    "IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE",
    "NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD",
    "TN","TX","UT","VT","VA","WA","WV","WI","WY",
}

# PADD region codes that EIA publishes weekly retail prices for.
# These are used as fallback for the 42 states without individual EIA data.
#   R1X = PADD 1A  New England (CT, ME, NH, RI, VT)
#   R1Y = PADD 1B  Central Atlantic (DC, DE, MD, NJ, PA)
#   R1Z = PADD 1C  Lower Atlantic (GA, NC, SC, VA, WV)
#   R20 = PADD 2   Midwest (IL, IN, IA, KS, KY, MI, MO, NE, ND, OK, SD, TN, WI)
#   R30 = PADD 3   Gulf Coast (AL, AR, LA, MS, NM)
#   R40 = PADD 4   Rocky Mountain (ID, MT, UT, WY)
#   R50 = PADD 5   West Coast (AK, AZ, HI, NV, OR — CA & WA have individual data)
VALID_PADDS = {"R1X", "R1Y", "R1Z", "R20", "R30", "R40", "R50"}


def eia_pages(api_key: str, start_date: str) -> Iterator[list[dict]]:
    """
    Yield pages of EIA weekly regular gasoline retail records from start_date.
    Each record has: period (YYYY-MM-DD), duoarea (e.g. SCA), value (float).
    """
    offset = 0
    session = requests.Session()

    while True:
        params = {
            "api_key":              api_key,
            "frequency":            "weekly",
            "data[]":               "value",
            "facets[product][]":    "EPM0",   # regular gasoline
            "facets[process][]":    "PTE",    # retail price
            "sort[0][column]":      "period",
            "sort[0][direction]":   "asc",
            "start":                start_date,
            "length":               PAGE_SIZE,
            "offset":               offset,
        }

        for attempt in range(3):
            try:
                resp = session.get(EIA_URL, params=params, timeout=30)
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    print(f"  [ERROR] EIA request failed after 3 attempts: {exc}", file=sys.stderr)
                    raise
                wait = 2 ** attempt
                print(f"  [WARN]  Retrying in {wait}s ({exc})")
                time.sleep(wait)

        body = resp.json()
        rows = body.get("response", {}).get("data", [])
        total = int(body.get("response", {}).get("total", 0))

        if not rows:
            break

        yield rows
        offset += len(rows)

        print(f"  fetched {offset:,} / {total:,} rows from EIA")

        if offset >= total:
            break


def to_area_code(duoarea: str) -> str | None:
    """
    Map an EIA duoarea code to the key we store in the DB.

    - State codes ('S' + 2-letter abbr, e.g. SCA) → state abbreviation (e.g. 'CA')
    - PADD region codes (R1X, R1Y, R1Z, R20, R30, R40, R50) → kept as-is
    - Everything else (national 'U', metro areas, aggregated regions like R10) → None
    """
    if not duoarea:
        return None
    # PADD region codes we care about
    if duoarea in VALID_PADDS:
        return duoarea
    # Individual state codes: length 3, starts with 'S'
    if len(duoarea) == 3 and duoarea.startswith("S"):
        abbr = duoarea[1:]
        return abbr if abbr in VALID_STATES else None
    return None


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_connection(args):
    return psycopg2.connect(
        host=args.db_host,
        port=args.db_port,
        dbname=args.db_name,
        user=args.db_username,
        password=args.db_password,
    )


UPSERT_WEEKLY = """
INSERT INTO prices_weekly (state, week_start, avg_price, grade)
VALUES %s
ON CONFLICT (state, week_start, grade) DO UPDATE
    SET avg_price  = EXCLUDED.avg_price,
        created_at = now()
"""

UPSERT_MONTHLY = """
INSERT INTO prices_monthly (state, year_month, avg_price, min_price, max_price, grade)
SELECT
    state,
    date_trunc('month', week_start)::date AS year_month,
    ROUND(AVG(avg_price)::numeric, 3)     AS avg_price,
    ROUND(MIN(avg_price)::numeric, 3)     AS min_price,
    ROUND(MAX(avg_price)::numeric, 3)     AS max_price,
    grade
FROM prices_weekly
GROUP BY state, date_trunc('month', week_start), grade
ON CONFLICT (state, year_month, grade) DO UPDATE
    SET avg_price = EXCLUDED.avg_price,
        min_price = EXCLUDED.min_price,
        max_price = EXCLUDED.max_price
"""

UPSERT_YEARLY = """
INSERT INTO prices_yearly (state, year, avg_price, min_price, max_price, grade)
SELECT
    state,
    EXTRACT(year FROM week_start)::smallint AS year,
    ROUND(AVG(avg_price)::numeric, 3)       AS avg_price,
    ROUND(MIN(avg_price)::numeric, 3)       AS min_price,
    ROUND(MAX(avg_price)::numeric, 3)       AS max_price,
    grade
FROM prices_weekly
GROUP BY state, EXTRACT(year FROM week_start), grade
ON CONFLICT (state, year, grade) DO UPDATE
    SET avg_price = EXCLUDED.avg_price,
        min_price = EXCLUDED.min_price,
        max_price = EXCLUDED.max_price
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Backfill EIA gas price data into the local DB.")
    parser.add_argument("--years",   type=int, default=3,  help="Years of history to fetch (default: 3)")
    parser.add_argument("--api-key", type=str, default="", help="EIA API key (overrides EIA_API_KEY env var)")
    parser.add_argument("--db-host",     default=os.environ.get("DB_HOST",     "localhost"))
    parser.add_argument("--db-port",     default=int(os.environ.get("DB_PORT", "5432")), type=int)
    parser.add_argument("--db-name",     default=os.environ.get("DB_NAME",     "gas_prices"))
    parser.add_argument("--db-username", default=os.environ.get("DB_USERNAME", "gas_price_admin"))
    parser.add_argument("--db-password", default=os.environ.get("DB_PASSWORD", "localpassword"))
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("EIA_API_KEY", "")
    if not api_key:
        sys.exit("ERROR: EIA_API_KEY not set. Pass --api-key or set the environment variable.")

    start_date = (date.today() - timedelta(days=365 * args.years)).strftime("%Y-%m-%d")
    print(f"Backfill: fetching {args.years} year(s) of EIA data from {start_date}")
    print(f"Database: {args.db_username}@{args.db_host}:{args.db_port}/{args.db_name}")

    # ── Connect ──────────────────────────────────────────────────────────────
    print("\nConnecting to database…")
    conn = get_connection(args)
    conn.autocommit = False
    cur = conn.cursor()

    # ── Fetch + upsert weekly rows ───────────────────────────────────────────
    print("\nFetching from EIA API…")
    total_inserted = 0
    total_skipped  = 0
    batch: list[tuple] = []

    for page in eia_pages(api_key, start_date):
        for row in page:
            state = to_area_code(row.get("duoarea", ""))
            value = row.get("value")
            period = row.get("period")

            if state is None or value is None or period is None:
                total_skipped += 1
                continue

            try:
                price = round(float(value), 3)
            except (TypeError, ValueError):
                total_skipped += 1
                continue

            batch.append((state, period, price, "regular"))

        # Flush every 2 000 rows so progress is visible
        if len(batch) >= 2000:
            psycopg2.extras.execute_values(cur, UPSERT_WEEKLY, batch, page_size=500)
            conn.commit()
            total_inserted += len(batch)
            print(f"  upserted {total_inserted:,} weekly rows so far…")
            batch = []

    # Final flush
    if batch:
        psycopg2.extras.execute_values(cur, UPSERT_WEEKLY, batch, page_size=500)
        conn.commit()
        total_inserted += len(batch)

    print(f"\n  weekly rows upserted : {total_inserted:,}")
    print(f"  rows skipped (non-state / null) : {total_skipped:,}")

    # ── Recompute monthly rollup ─────────────────────────────────────────────
    print("\nRecomputing monthly rollup…")
    cur.execute(UPSERT_MONTHLY)
    monthly_count = cur.rowcount
    conn.commit()
    print(f"  monthly rows upserted: {monthly_count:,}")

    # ── Recompute yearly rollup ──────────────────────────────────────────────
    print("Recomputing yearly rollup…")
    cur.execute(UPSERT_YEARLY)
    yearly_count = cur.rowcount
    conn.commit()
    print(f"  yearly rows upserted : {yearly_count:,}")

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
