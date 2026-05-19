"""
FastAPI application definition.

Registers exception handlers, rate-limit middleware, and the prices router.
The DB engine and Redis pool are initialised lazily on the first request
(see db.py and cache.py) so that cold-start time stays minimal.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from exceptions import DatabaseUnavailableError, InvalidPeriodError, StateNotFoundError
from routers import prices

# ---------------------------------------------------------------------------
# Structured logging — same pattern as the ingest / transform Lambdas
# ---------------------------------------------------------------------------

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def log(level: int, event: str, **kwargs: Any) -> None:
    logger.log(
        level,
        json.dumps({
            "event":    event,
            "function": os.environ.get("AWS_LAMBDA_FUNCTION_NAME"),
            **kwargs,
        }),
    )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="US Gas Price API",
    version="1.0.0",
    description="Weekly US retail gas prices by state, sourced from the EIA Open Data API.",
    docs_url="/docs",
    redoc_url=None,
)


# ---------------------------------------------------------------------------
# CORS — allow all origins so the frontend can call the API both locally
# (http://localhost:3000) and from CloudFront in production.
# API Gateway also adds CORS headers in production; these don't conflict.
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Exception handlers — always return structured JSON, never raw 500s
# ---------------------------------------------------------------------------

@app.exception_handler(StateNotFoundError)
async def state_not_found_handler(request: Request, exc: StateNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"error": "state_not_found", "detail": str(exc)},
    )


@app.exception_handler(InvalidPeriodError)
async def invalid_period_handler(request: Request, exc: InvalidPeriodError):
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_period", "detail": str(exc)},
    )


@app.exception_handler(DatabaseUnavailableError)
async def db_unavailable_handler(request: Request, exc: DatabaseUnavailableError):
    log(logging.ERROR, "db_unavailable", path=str(request.url.path))
    return JSONResponse(
        status_code=503,
        content={"error": "database_unavailable", "detail": "Please try again later."},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "invalid_params", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    log(logging.ERROR, "unhandled_error", path=str(request.url.path), error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error"},
    )


# ---------------------------------------------------------------------------
# Rate-limit middleware — per-IP sliding window using Redis counters.
# If Redis is unavailable the request is passed through without limiting —
# never block traffic because the cache is down.
# ---------------------------------------------------------------------------

RATE_LIMIT = 60   # max requests per window per IP
WINDOW     = 60   # window size in seconds


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Skip rate limiting on health checks to avoid false alarm noise
    if request.url.path == "/v1/health":
        return await call_next(request)

    ip  = request.client.host if request.client else "unknown"
    key = f"rl:{ip}"
    try:
        from cache import get_client as get_redis
        import redis as redis_lib
        client = get_redis()
        count  = client.incr(key)
        if count == 1:
            client.expire(key, WINDOW)
        if count > RATE_LIMIT:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limit_exceeded", "retry_after": WINDOW},
                headers={"Retry-After": str(WINDOW)},
            )
    except Exception:
        pass  # Redis down → skip rate limiting, never block requests

    response = await call_next(request)
    log(
        logging.INFO, "request",
        method=request.method,
        path=str(request.url.path),
        status=response.status_code,
        ip=ip,
    )
    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(prices.router, prefix="/v1")
