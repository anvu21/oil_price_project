"""
Lambda entry point — wraps the FastAPI app with Mangum.

Mangum translates API Gateway HTTP API (v2) proxy events into ASGI-compatible
requests and passes responses back. lifespan="off" because Lambda containers
do not persist between invocations in a way that supports ASGI lifespan events.
"""
from mangum import Mangum
from main import app

# API Gateway HTTP API v2 sends payload_format_version "2.0" by default.
# Mangum auto-detects the version, so no explicit config is needed.
handler = Mangum(app, lifespan="off")
