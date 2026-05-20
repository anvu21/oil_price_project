"""
FastAPI application definition.

Registers exception handlers, security middleware, rate-limit middleware,
and the prices router.  The DB engine and Redis pool are initialised lazily
on the first request (see db.py and cache.py) so that cold-start stays minimal.

OWASP API Security Top 10 coverage
───────────────────────────────────
API1  Broken Object Level Authorization — N/A: no user-specific objects.
API2  Broken Authentication            — N/A: public read-only API.
API3  Excessive Data Exposure          — docs_url disabled in prod; error
                                         handlers never expose stack traces.
API4  Lack of Resources & Rate Limiting— two-layer: API Gateway (100 req/s,
                                         10 k/day) + per-IP Redis counter.
API5  Broken Function Level Auth       — N/A: only GET endpoints, no writes.
API6  Mass Assignment                  — N/A: no request bodies accepted.
API7  Security Misconfiguration        — CORS restricted to known origin;
                                         security headers on every response.
API8  Injection                        — SQLAlchemy parameterized queries
                                         throughout; date params validated.
API9  Improper Assets Management       — single versioned namespace (/v1/).
API10 Insufficient Logging & Monitoring— structured JSON logs on every
                                         request; CloudWatch alarms wired up.
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
# Environment
# ---------------------------------------------------------------------------

_ENV = os.environ.get("ENVIRONMENT", "prod")   # "local" | "prod"
_IS_PROD = _ENV != "local"

# ---------------------------------------------------------------------------
# FastAPI app
#
# OWASP API3 — Excessive Data Exposure:
#   The interactive OpenAPI UI (/docs) is disabled in production so that
#   the API surface is not publicly documented and enumerable.  Redoc is
#   also disabled.  The raw schema (/openapi.json) is likewise hidden.
# ---------------------------------------------------------------------------

app = FastAPI(
    title="US Gas Price API",
    version="1.0.0",
    description="Weekly US retail gas prices by state, sourced from the EIA Open Data API.",
    # Disable all documentation UIs in production (OWASP API3).
    docs_url    = None if _IS_PROD else "/docs",
    redoc_url   = None,
    openapi_url = None if _IS_PROD else "/openapi.json",
)


# ---------------------------------------------------------------------------
# CORS
#
# OWASP API7 — Security Misconfiguration:
#   Restrict the Access-Control-Allow-Origin header to the known frontend
#   origin rather than reflecting * .  For a public read-only API this is
#   not a strict security boundary (CORS is enforced by browsers, not servers)
#   but it prevents unintended cross-origin reads from other sites and follows
#   the principle of least privilege.
#
#   Set ALLOWED_ORIGIN in Terraform (or .env for local dev).
#   Defaults to the CloudFront distribution URL.
# ---------------------------------------------------------------------------

_ALLOWED_ORIGIN = os.environ.get(
    "ALLOWED_ORIGIN",
    "https://d29v5i05cdp0sg.cloudfront.net",    # production CloudFront domain
)

# Always allow localhost for local development regardless of env var.
_CORS_ORIGINS = [_ALLOWED_ORIGIN] if _IS_PROD else [_ALLOWED_ORIGIN, "http://localhost:5173", "http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,   # NOT "*" — explicitly scoped (OWASP API7)
    allow_methods=["GET"],          # read-only API; no POST/PUT/DELETE
    allow_headers=["Content-Type", "Accept"],
)


# ---------------------------------------------------------------------------
# Exception handlers — always return structured JSON, never raw 500s
#
# OWASP API3 — Excessive Data Exposure:
#   The unhandled_error_handler catches all unexpected exceptions and returns
#   a generic message.  The real error is logged to CloudWatch but never
#   included in the response body, so internal details (file paths, SQL,
#   library versions) are never leaked to the caller.
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
        content={"error": "invalid_params", "detail": str(exc)},
    )


@app.exception_handler(DatabaseUnavailableError)
async def db_unavailable_handler(request: Request, exc: DatabaseUnavailableError):
    log(logging.ERROR, "db_unavailable", path=str(request.url.path))
    return JSONResponse(
        status_code=503,
        # Generic message — never reveal whether it's a connection error,
        # timeout, or authentication failure (OWASP API3).
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
    # Log the real exception internally but return nothing useful to the caller.
    log(logging.ERROR, "unhandled_error", path=str(request.url.path), error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error"},   # no detail — OWASP API3
    )


# ---------------------------------------------------------------------------
# Security headers middleware
#
# OWASP API7 — Security Misconfiguration:
#   Add standard defensive headers to every response.  Even though this is a
#   JSON API (no HTML rendered), the headers guard against MIME-sniffing,
#   clickjacking (if the response is ever framed), and protocol downgrade.
# ---------------------------------------------------------------------------

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)

    # Prevent browsers from MIME-sniffing the content type.
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Deny embedding in iframes — irrelevant for a JSON API but costs nothing.
    response.headers["X-Frame-Options"] = "DENY"

    # Tell browsers to enforce HTTPS for 2 years and include subdomains.
    # Preload omitted intentionally — requires HSTS preload-list submission.
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"

    # Suppress the Referer header so downstream services don't see our URL.
    response.headers["Referrer-Policy"] = "no-referrer"

    # Disable all browser features not needed by this API.
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"

    # API responses must not be stored by shared caches or browsers.
    # Individual route TTLs are managed at the CloudFront / Redis layer.
    response.headers["Cache-Control"] = "no-store"

    return response


# ---------------------------------------------------------------------------
# Real client IP helper
#
# OWASP API4 — Lack of Resources & Rate Limiting:
#   The API sits behind CloudFront → API Gateway → Lambda.  By the time
#   a request reaches Lambda, request.client.host is the IP of the *last*
#   hop (API Gateway's internal address), not the user's real IP.
#   CloudFront appends the original viewer IP as the first entry in
#   X-Forwarded-For; we take that value for rate-limit keying.
#
#   Security note: X-Forwarded-For can be spoofed by clients who bypass
#   CloudFront and hit API Gateway directly.  For a public read-only API
#   this is an acceptable risk — rate limiting is a DoS mitigation, not
#   an access control.  If strict enforcement is needed, lock API Gateway
#   to CloudFront IP ranges via a WAF rule.
# ---------------------------------------------------------------------------

def _real_ip(request: Request) -> str:
    """Return the best-effort real client IP address."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        # X-Forwarded-For: <client>, <proxy1>, <proxy2>
        # The leftmost address is the original client IP.
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Rate-limit middleware — per-IP sliding window using Redis counters.
#
# OWASP API4 — Lack of Resources & Rate Limiting:
#   Layer 1: API Gateway throttle (100 req/s burst, 10 k req/day).
#   Layer 2: this middleware — 60 requests per 60-second window per IP.
#
#   If Redis is unavailable (REDIS_ENABLED=false or network error) the
#   request is passed through — Layer 1 remains active.  Rate-limiting
#   failures must never block legitimate traffic.
#
#   Race-condition note: a naive INCR + EXPIRE pair can leave a key without
#   a TTL if the process crashes between the two commands.  We use a Redis
#   pipeline to send both commands atomically in one round trip, preventing
#   a "sticky" counter that never expires.
# ---------------------------------------------------------------------------

RATE_LIMIT = 60   # max requests per window per IP
WINDOW     = 60   # window size in seconds


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Health checks are excluded from rate limiting to avoid CloudWatch alarm
    # noise caused by the frequent synthetic canary probes.
    if request.url.path == "/v1/health":
        return await call_next(request)

    ip  = _real_ip(request)
    key = f"rl:{ip}"

    try:
        from cache import get_client as get_redis
        client = get_redis()

        # Pipeline ensures INCR + EXPIRE are sent atomically — no orphaned
        # counters if Lambda is killed between the two commands (OWASP API4).
        pipe  = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, WINDOW)
        count, _ = pipe.execute()

        if count > RATE_LIMIT:
            log(logging.WARNING, "rate_limit_exceeded", ip=ip, count=count)
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limit_exceeded", "retry_after": WINDOW},
                headers={"Retry-After": str(WINDOW)},
            )
    except Exception:
        # Redis unavailable — fall through; API Gateway Layer 1 still protects.
        pass

    response = await call_next(request)

    # OWASP API10 — Insufficient Logging & Monitoring:
    #   Log every request with method, path, status and real client IP.
    #   CloudWatch Insights can query these structured logs for anomaly detection.
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
