"""
Redis cache helpers — cache-aside pattern.

All public functions are wrapped in try/except. Cache failures must NEVER
propagate to the caller; the API falls through to RDS on any Redis error.

Connectivity note: The API Lambda runs inside the VPC private subnet.
Upstash Redis (external, port 6379) is unreachable without a NAT Gateway.
Set REDIS_ENABLED=false (the default when deployed in VPC) to skip all Redis
calls entirely and avoid the OS-level TCP retransmit hang (~75s) that occurs
when SYN packets are silently dropped with no route to the internet.

To enable caching: add a NAT Gateway (or move the Lambda outside the VPC with
an RDS Proxy) and set REDIS_ENABLED=true.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
import redis

# ---------------------------------------------------------------------------
# Feature flag — set REDIS_ENABLED=false when Lambda cannot reach Upstash
# (e.g. VPC private subnet with no NAT Gateway).
# ---------------------------------------------------------------------------
_REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "true").lower() == "true"

logger = logging.getLogger(__name__)

# Module-level pool — created once per Lambda container lifetime.
_pool: redis.ConnectionPool | None = None
_redis_url: str | None = None   # cached after first Secrets Manager fetch


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_redis_url() -> str:
    """
    Return the Redis connection URL.

    Resolution order:
      1. REDIS_URL env var (local dev / Docker Compose — skips Secrets Manager).
      2. REDIS_SECRET_ARN env var → fetch from Secrets Manager (production).
    """
    # Local dev: Redis URL provided directly (e.g. redis://redis:6379)
    direct_url = os.environ.get("REDIS_URL", "")
    if direct_url:
        return direct_url

    secret_arn = os.environ.get("REDIS_SECRET_ARN", "")
    if not secret_arn:
        return ""
    client = boto3.client("secretsmanager")
    try:
        response = client.get_secret_value(SecretId=secret_arn)
        return response["SecretString"]
    except Exception as exc:
        logger.warning("Failed to fetch Redis URL from Secrets Manager: %s", exc)
        return ""


def _ensure_pool() -> redis.ConnectionPool | None:
    """Return the module-level connection pool, creating it on first call."""
    if not _REDIS_ENABLED:
        return None  # fast-path: skip Secrets Manager fetch + TCP connect attempt
    global _pool, _redis_url
    if _pool is not None:
        return _pool
    if _redis_url is None:
        _redis_url = _get_redis_url()
    if not _redis_url:
        return None
    try:
        _pool = redis.ConnectionPool.from_url(
            _redis_url,
            decode_responses=True,
            socket_timeout=5,           # fail fast if Upstash is unreachable
            socket_connect_timeout=5,
            max_connections=2,
        )
        return _pool
    except Exception as exc:
        logger.warning("Failed to create Redis connection pool: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_client() -> redis.Redis:
    """
    Return a Redis client using the module-level pool.
    Raises redis.RedisError if the pool could not be initialised.
    """
    pool = _ensure_pool()
    if pool is None:
        raise redis.RedisError("Redis pool not initialised — URL unavailable")
    return redis.Redis(connection_pool=pool)


def cache_get(key: str) -> Any | None:
    """
    Return the cached value for key, or None on cache miss or any error.
    Deserialises JSON automatically.
    """
    if not _REDIS_ENABLED:
        return None
    try:
        val = get_client().get(key)
        return json.loads(val) if val else None
    except Exception:
        return None  # cache miss — caller will query RDS


def cache_set(key: str, value: Any, ttl: int = 3600) -> None:
    """
    Store value in cache with TTL seconds. Silently ignores any Redis error.
    Serialises value to JSON automatically.
    """
    if not _REDIS_ENABLED:
        return
    try:
        get_client().setex(key, ttl, json.dumps(value))
    except Exception:
        pass  # non-fatal — RDS is the source of truth


def cache_ping() -> bool:
    """Return True if Redis is reachable (used by /v1/health)."""
    if not _REDIS_ENABLED:
        return False
    try:
        return get_client().ping()
    except Exception:
        return False
