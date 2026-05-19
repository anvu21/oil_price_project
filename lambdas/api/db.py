"""
SQLAlchemy engine initialisation for the API Lambda.

The engine is created once per Lambda container (cold-start) and reused across
warm invocations. The DB password is fetched from Secrets Manager via the VPC
Interface endpoint on the first request.

Connection pool settings are deliberately small (pool_size=1) because each
Lambda container handles one concurrent request at a time. pool_pre_ping=True
recovers from idle-timeout disconnects on warm starts.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

_engine: Engine | None = None


def _fetch_secret(secret_arn: str) -> str:
    """Fetch a plain-string secret from Secrets Manager."""
    client = boto3.client("secretsmanager")
    try:
        response = client.get_secret_value(SecretId=secret_arn)
    except ClientError as exc:
        logger.error("Failed to fetch secret %s: %s", secret_arn, exc)
        raise
    return response["SecretString"]


def _build_engine() -> Engine:
    # Local dev: DB_PASSWORD set directly in environment (Docker Compose).
    # Production: fetch from Secrets Manager via the VPC Interface endpoint.
    direct_password = os.environ.get("DB_PASSWORD")
    if direct_password:
        db_password = direct_password
        logger.info("db: using DB_PASSWORD env var (local dev)")
    else:
        logger.info("db: fetching secret from Secrets Manager")
        db_password = _fetch_secret(os.environ["DB_SECRET_ARN"])
        logger.info("db: secret fetched OK")

    host = os.environ["DB_HOST"]
    name = os.environ["DB_NAME"]
    user = os.environ["DB_USERNAME"]
    port = os.environ.get("DB_PORT", "5432")
    url  = f"postgresql+psycopg2://{user}:{db_password}@{host}:{port}/{name}"

    # Local Postgres container doesn't have TLS certs; RDS enforces TLS.
    is_local = os.environ.get("ENVIRONMENT") == "local"
    ssl_mode = "prefer" if is_local else "require"
    # More connections for local dev (uvicorn can be multi-threaded); Lambda is single-request.
    pool_sz  = 5 if is_local else 1

    logger.info(
        "db: creating engine (host=%s name=%s user=%s sslmode=%s pool=%d)",
        host, name, user, ssl_mode, pool_sz,
    )
    engine = create_engine(
        url,
        pool_size=pool_sz,
        max_overflow=0,
        pool_pre_ping=True,  # detect stale connections from warm-start idle timeout
        connect_args={
            "connect_timeout": 10,
            "sslmode": ssl_mode,
        },
    )
    logger.info("db: engine object created (no TCP connection yet)")
    return engine


def get_engine() -> Engine:
    """Return the module-level engine, building it on first call (cold-start)."""
    global _engine
    if _engine is None:
        logger.info("Building SQLAlchemy engine (cold start)")
        _engine = _build_engine()
    return _engine


@contextmanager
def get_db() -> Generator[Connection, None, None]:
    """
    Yield a SQLAlchemy Connection and close it on exit.

    Uses engine.connect() directly — the same approach as the transform Lambda —
    which avoids the ORM Session layer (autobegin, autoflush) that can hang
    when establishing the first connection inside a VPC Lambda.

    Usage:
        with get_db() as db:
            rows = db.execute(text("SELECT ...")).fetchall()
    """
    engine = get_engine()
    logger.info("db: opening connection")
    with engine.connect() as conn:
        yield conn
