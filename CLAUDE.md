# US Gas Price Dashboard — Project Brief for Claude Code

## What we're building

A full-stack AWS-native application that displays weekly US gas prices by state, sourced from the EIA (US Energy Information Administration) public API. Users can view average gas prices per state and toggle between weekly, monthly, and yearly aggregations. The app is a personal portfolio project designed to demonstrate production-grade AWS skills: serverless ETL pipelines, FastAPI backends, Redis caching, rate limiting, structured error handling, CloudWatch alerting, Lambda rollback, and Terraform IaC.

---

## Tech stack

| Layer | Technology |
|---|---|
| ETL / backend | Python 3.12, FastAPI, Pydantic v2, Mangum |
| Database | AWS RDS PostgreSQL 15 (inside VPC) |
| Cache | Upstash Redis (serverless, external — not inside VPC) |
| Compute | AWS Lambda (all functions) |
| Scheduling | AWS EventBridge (weekly cron) |
| Failure handling | AWS SQS Dead Letter Queue |
| Object storage | AWS S3 (raw + processed data lake) |
| API layer | AWS API Gateway (HTTP API) |
| Observability | AWS CloudWatch (logs, alarms, dashboards) |
| Alerting | AWS SNS (email notifications) |
| IaC | Terraform >= 1.7, modularized |
| CI/CD | GitHub Actions |
| Frontend | React 18, Recharts, Tailwind CSS |
| Frontend hosting | AWS S3 + CloudFront |

---

## Architecture overview

```
[EventBridge weekly] --> [Lambda: ingest (outside VPC)] --> [EIA API]  (internet direct)
                                          --> [S3: raw/]        --> [Lambda: transform (private subnet)]
                                          --> [SQS DLQ]                    |
                                                                   [RDS Postgres]   (via private subnet)
                                                                   [Upstash Redis]  (invalidate via HTTPS — non-fatal)
                                                                   [S3 Gateway endpoint]   (free, no internet needed)
                                                                   [Secrets Manager endpoint] (~$7/mo Interface endpoint)

[React app] --> [API Gateway] --> [Lambda: API (outside VPC) / FastAPI+Mangum]
                                          --> [Upstash Redis] (cache hit → return, via HTTPS)
                                          --> [RDS]           (cache miss → query → write Redis)
                                          --> [CloudWatch]    (every request logged)

[CloudWatch alarms] --> [SNS] --> [email]
[Terraform + GitHub Actions] --> deploys everything
```

**Key networking decision:** Lambda functions attached to a VPC never receive a public IP, even in a public subnet — they need a NAT Gateway for internet access. To avoid the ~$33/mo NAT cost:
- **Ingest Lambda** runs *outside* the VPC → reaches EIA API + S3 + Secrets Manager directly over the internet.
- **Transform Lambda** runs *inside* the VPC (private subnet) → reaches S3 via a free Gateway endpoint, Secrets Manager via an Interface endpoint (~$7/mo), and RDS directly over the private subnet. Upstash Redis invalidation goes over the internet via the endpoint but is non-fatal if it fails (TTL handles staleness).
- **API Lambda** (Phase 4) runs *inside* the VPC (private subnet) → reaches RDS directly. Upstash Redis is unreachable without a NAT Gateway, so `REDIS_ENABLED=false` is set; the cache-aside code is in place but bypassed. To enable Redis: add a NAT Gateway (~$33/mo) or move the Lambda outside the VPC with an RDS Proxy.

---

## Project structure

```
gas-price-dashboard/
├── CLAUDE.md                        # this file
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── backend.tf                   # S3 state + DynamoDB lock
│   └── modules/
│       ├── lambda/
│       ├── storage/
│       ├── networking/              # VPC, subnets, security groups
│       ├── database/                # RDS only (no ElastiCache — using Upstash)
│       └── monitoring/              # CloudWatch, SNS, alarms
├── lambdas/
│   ├── ingest/
│   │   ├── handler.py
│   │   ├── eia_client.py
│   │   ├── models.py                # Pydantic input models
│   │   └── requirements.txt
│   ├── transform/
│   │   ├── handler.py
│   │   ├── aggregator.py
│   │   ├── models.py
│   │   └── requirements.txt
│   └── api/
│       ├── handler.py               # Mangum entry point
│       ├── main.py                  # FastAPI app
│       ├── routers/
│       │   └── prices.py
│       ├── models.py                # Pydantic response models
│       ├── db.py                    # RDS connection (SQLAlchemy)
│       ├── cache.py                 # Redis client + helpers
│       └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── StateMap.jsx         # choropleth US map
│   │   │   ├── PriceChart.jsx       # line chart for selected state
│   │   │   └── PeriodToggle.jsx     # weekly / monthly / yearly
│   │   └── api/
│   │       └── client.js
│   └── package.json
├── scripts/
│   └── backfill.py                  # seed historical EIA data
└── .github/
    └── workflows/
        ├── deploy-infra.yml
        └── deploy-app.yml
```

---

## Data source

**EIA Open Data API** — free, no rate limits for reasonable use.
- Registration: https://www.eia.gov/opendata/
- Endpoint: `https://api.eia.gov/v2/petroleum/pri/gnd/data/`
- Key parameters:
  - `frequency=weekly`
  - `data[]=value`
  - `facets[product][]=EPM0`  (regular gasoline)
  - `facets[duoarea][]=<state code>`  (e.g. `SCA` for California)
  - `sort[0][column]=period&sort[0][direction]=desc`
  - `api_key=<your key>`
- Response shape: `{ response: { data: [ { period, duoarea, value, units } ] } }`
- State area codes follow EIA convention: `SCA`, `STX`, `SFL`, etc. (S + FIPS abbreviation)
- Store your EIA API key in AWS Secrets Manager as `gas-price-prod/eia-api-key`

---

## Database schema (RDS Postgres)

```sql
-- Raw weekly prices (one row per state per week)
CREATE TABLE prices_weekly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(2)    NOT NULL,   -- e.g. 'CA'
    week_start  DATE          NOT NULL,
    avg_price   NUMERIC(5,3)  NOT NULL,   -- price per gallon USD
    grade       VARCHAR(20)   NOT NULL DEFAULT 'regular',
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (state, week_start, grade)
);

-- Monthly rollup (computed by transform Lambda)
CREATE TABLE prices_monthly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(2)    NOT NULL,
    year_month  DATE          NOT NULL,   -- first day of month
    avg_price   NUMERIC(5,3)  NOT NULL,
    min_price   NUMERIC(5,3)  NOT NULL,
    max_price   NUMERIC(5,3)  NOT NULL,
    grade       VARCHAR(20)   NOT NULL DEFAULT 'regular',
    UNIQUE (state, year_month, grade)
);

-- Yearly rollup
CREATE TABLE prices_yearly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(2)    NOT NULL,
    year        SMALLINT      NOT NULL,
    avg_price   NUMERIC(5,3)  NOT NULL,
    min_price   NUMERIC(5,3)  NOT NULL,
    max_price   NUMERIC(5,3)  NOT NULL,
    grade       VARCHAR(20)   NOT NULL DEFAULT 'regular',
    UNIQUE (state, year, grade)
);

-- ETL audit log
CREATE TABLE ingest_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    status           VARCHAR(20) NOT NULL,   -- success / failed / partial
    records_fetched  INT,
    error_message    TEXT,
    s3_path          TEXT
);

-- Indexes
CREATE INDEX ON prices_weekly (state, week_start DESC);
CREATE INDEX ON prices_monthly (state, year_month DESC);
CREATE INDEX ON prices_yearly (state, year DESC);
```

---

## API endpoints (FastAPI)

All endpoints live under `/v1/`. API Gateway enforces: **100 req/s rate, 200 burst, 10,000 req/day quota**.

```
GET /v1/prices/{state}
  Query params: period=weekly|monthly|yearly (default: weekly)
                grade=regular|midgrade|premium|diesel (default: regular)
                from=YYYY-MM  (optional)
                to=YYYY-MM    (optional)
  Cache: Redis key = prices:{state}:{period}:{grade}:{from}:{to}, TTL = 3600s
  Returns: { state, period, grade, data: [ { date, avg_price } ] }

GET /v1/prices/latest
  Returns most recent week's price for all 50 states + DC.
  Cache: Redis key = prices:latest, TTL = 3600s
  Used to populate the choropleth map on initial load.

GET /v1/prices/national
  Returns national average (mean across all states) for a given period.
  Query params: same as /{state}
  Cache: Redis key = prices:national:{period}:{grade}, TTL = 3600s

GET /v1/prices/compare
  Query params: states=CA,TX,FL (comma-separated), period, grade
  Returns prices for multiple states in one response.
  Cache: Redis key = prices:compare:{sorted_states}:{period}:{grade}, TTL = 3600s

GET /v1/states
  Returns list of all available states with name, abbreviation, EIA area code.
  Cache: TTL = 86400s (24hr — this data never changes)

GET /v1/health
  Returns: { status, db_connected, cache_connected, last_ingest_at, last_ingest_status }
  NOT cached. Used as CloudWatch alarm source.
```

---

## Caching strategy (Redis)

Use the **cache-aside pattern**:
1. Check Redis for key
2. On hit → return immediately
3. On miss → query RDS → write result to Redis with TTL → return

Cache invalidation: after each successful transform Lambda run, delete all keys matching `prices:*` using `SCAN` + `DEL`. Do NOT use `FLUSHDB` — too blunt.

Redis connection: use `redis-py` with a connection pool. The Redis URL is stored in Secrets Manager (`gas-price-prod/redis-url`) and fetched at Lambda cold-start via the `REDIS_SECRET_ARN` env var. The API Lambda will also have a `REDIS_URL` env var set directly if preferred.

```python
# cache.py pattern
import redis
import json
from functools import wraps

pool = redis.ConnectionPool.from_url(os.environ["REDIS_URL"])  # fetched from Secrets Manager at cold-start

def get_client():
    return redis.Redis(connection_pool=pool)

def cache_get(key: str):
    try:
        val = get_client().get(key)
        return json.loads(val) if val else None
    except redis.RedisError:
        return None  # cache failure must never break the API

def cache_set(key: str, value, ttl: int = 3600):
    try:
        get_client().setex(key, ttl, json.dumps(value))
    except redis.RedisError:
        pass  # silent fail — RDS is the source of truth
```

**Important:** cache errors must never propagate to the user. Always wrap Redis calls in try/except and fall through to RDS.

---

## Error handling

### FastAPI exception handlers

```python
# Typed errors — always return structured JSON, never raw 500s
class StateNotFoundError(Exception): pass
class InvalidPeriodError(Exception): pass
class DatabaseUnavailableError(Exception): pass

@app.exception_handler(StateNotFoundError)
async def state_not_found(request, exc):
    return JSONResponse(status_code=404, content={"error": "state_not_found", "detail": str(exc)})

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422, content={"error": "invalid_params", "detail": exc.errors()})

@app.exception_handler(Exception)
async def unhandled(request, exc):
    logger.error("unhandled_error", exc_info=exc, extra={"path": request.url.path})
    return JSONResponse(status_code=500, content={"error": "internal_error"})
```

### Lambda error handling + DLQ

Ingest Lambda should:
1. Catch EIA API errors (network timeout, 429, 5xx) with exponential backoff (3 retries)
2. On final failure → raise exception so Lambda marks invocation as failed
3. EventBridge → Lambda is configured with a DLQ (SQS) — failed invocations land there
4. CloudWatch alarm on DLQ depth > 0 → SNS alert

```python
# Retry pattern in ingest Lambda
import time

def fetch_with_retry(url, params, max_retries=3):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)  # 1s, 2s, 4s
```

### Structured logging

Every Lambda must emit structured JSON logs to CloudWatch:

```python
import json, logging, os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def log(level, event, **kwargs):
    logger.log(level, json.dumps({
        "event": event,
        "function": os.environ.get("AWS_LAMBDA_FUNCTION_NAME"),
        **kwargs
    }))

# Usage
log(logging.INFO, "ingest_complete", records=47, s3_path="raw/2025/03/17/")
log(logging.ERROR, "eia_fetch_failed", error=str(e), attempt=attempt)
```

---

## Rate limiting

Two layers:

**Layer 1 — API Gateway** (Terraform-managed):
```hcl
resource "aws_api_gateway_usage_plan" "default" {
  name = "gas-price-default"
  throttle_settings {
    rate_limit  = 100
    burst_limit = 200
  }
  quota_settings {
    limit  = 10000
    period = "DAY"
  }
}
```

**Layer 2 — FastAPI middleware** (per-IP using Redis counters):
```python
# middleware/rate_limit.py
from fastapi import Request
from fastapi.responses import JSONResponse

RATE_LIMIT = 60       # requests
WINDOW     = 60       # seconds

async def rate_limit_middleware(request: Request, call_next):
    ip = request.client.host
    key = f"rl:{ip}"
    try:
        client = get_redis_client()
        count = client.incr(key)
        if count == 1:
            client.expire(key, WINDOW)
        if count > RATE_LIMIT:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limit_exceeded", "retry_after": WINDOW},
                headers={"Retry-After": str(WINDOW)}
            )
    except redis.RedisError:
        pass  # if Redis is down, don't block requests
    return await call_next(request)
```

---

## Alerting (CloudWatch + SNS)

Create these alarms in the `monitoring` Terraform module:

| Alarm | Metric | Threshold | Action |
|---|---|---|---|
| Ingest Lambda errors | `Errors` | > 0 in 5min | SNS email |
| API Lambda error rate | `Errors / Invocations` | > 5% over 5min | SNS email |
| DLQ depth | `ApproximateNumberOfMessagesVisible` | > 0 | SNS email |
| RDS CPU | `CPUUtilization` | > 80% for 10min | SNS email |
| API p99 latency | `Duration p99` | > 3000ms | SNS email |
| Health check | `/v1/health` returns non-200 | 2 consecutive | SNS email |

```hcl
# Example alarm in monitoring module
resource "aws_cloudwatch_metric_alarm" "ingest_errors" {
  alarm_name          = "gas-price-ingest-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  dimensions = {
    FunctionName = var.ingest_function_name
  }
  alarm_actions = [var.sns_topic_arn]
}
```

---

## Rollback strategy

**Lambda rollback** (primary mechanism):
- Every deploy publishes a new Lambda version
- A `prod` alias always points to the live version
- Rollback = update alias to point to previous version number
- Terraform manages this via `aws_lambda_alias` + `aws_lambda_function` with `publish = true`

```hcl
resource "aws_lambda_function" "api" {
  publish = true   # creates a new numbered version on every deploy
  ...
}

resource "aws_lambda_alias" "api_prod" {
  name             = "prod"
  function_name    = aws_lambda_function.api.arn
  function_version = var.api_lambda_version  # override to roll back
}
```

To roll back: change `api_lambda_version` variable to previous version number → `terraform apply`.

**RDS rollback**:
- Enable automated backups: `backup_retention_period = 7` (7 days)
- Point-in-time recovery available from RDS console or AWS CLI

**Blue/green deploy** (stretch goal):
- Deploy new Lambda version → smoke test `/v1/health` → if healthy, shift alias → if errors spike within 5 min, auto-revert alias using a CloudWatch alarm + Lambda rollback function.

---

## Terraform module structure

```hcl
# terraform/main.tf — top-level wiring
module "networking" {
  source = "./modules/networking"
  # outputs: vpc_id, public_subnet_ids, private_subnet_ids, lambda_sg_id, rds_sg_id
  # No NAT Gateway — saves ~$33/mo. Internet access handled per-Lambda (see below).
  # Includes: S3 Gateway endpoint (free) + Secrets Manager Interface endpoint (~$7/mo)
  # These allow VPC-attached Lambdas to reach AWS services without NAT.
}

module "storage" {
  source      = "./modules/storage"
  # outputs: raw_bucket_name, processed_bucket_name, terraform_state_bucket
}

module "database" {
  source            = "./modules/database"
  vpc_id            = module.networking.vpc_id
  subnet_ids        = module.networking.private_subnet_ids
  rds_sg_id         = module.networking.rds_sg_id
  # RDS only — no ElastiCache. Redis is Upstash (external, provisioned on upstash.com)
  # outputs: rds_address, rds_db_name, db_secret_arn, redis_secret_arn
}

module "lambda" {
  source          = "./modules/lambda"
  vpc_id          = module.networking.vpc_id
  subnet_ids      = module.networking.private_subnet_ids  # transform Lambda only (VPC-attached)
  lambda_sg_id    = module.networking.lambda_sg_id
  raw_bucket_name = module.storage.raw_bucket_name
  raw_bucket_arn  = module.storage.raw_bucket_arn
  eia_api_key     = var.eia_api_key

  # Ingest Lambda has NO vpc_config — runs outside VPC for direct internet access
  # (EIA API + S3 + Secrets Manager reachable without NAT or VPC endpoints)

  # Transform Lambda IS VPC-attached (private subnet):
  #   S3 access        → S3 Gateway endpoint (free)
  #   Secrets Manager  → Interface endpoint (~$7/mo)
  #   RDS              → directly via private subnet
  #   Upstash Redis    → HTTPS invalidation (non-fatal if fails — TTL handles staleness)
  db_host          = module.database.rds_address
  db_name          = module.database.rds_db_name
  db_username      = var.db_username
  db_secret_arn    = module.database.db_secret_arn
  redis_secret_arn = module.database.redis_secret_arn
  # outputs: ingest_function_name, transform_function_name, dlq_url, dlq_arn, etc.
}

module "monitoring" {
  source                 = "./modules/monitoring"
  ingest_function_name   = module.lambda.ingest_function_name
  transform_function_name = module.lambda.transform_function_name
  dlq_arn                = module.lambda.dlq_arn
  alert_email            = var.alert_email
}
```

Remote state backend:
```hcl
# terraform/backend.tf
terraform {
  backend "s3" {
    bucket         = "gas-price-tf-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "gas-price-tf-lock"
    encrypt        = true
  }
}
```

---

## CI/CD (GitHub Actions)

```yaml
# .github/workflows/deploy-infra.yml
# Triggers on push to main that changes terraform/**
# Steps: checkout → setup terraform → terraform init → plan → apply

# .github/workflows/deploy-app.yml
# Triggers on push to main that changes lambdas/** or frontend/**
# Steps:
#   1. Run Python tests (pytest lambdas/)
#   2. Package each Lambda (pip install -r requirements.txt -t ./package && zip)
#   3. Upload zip to S3
#   4. aws lambda update-function-code
#   5. aws lambda publish-version
#   6. (frontend) npm build → aws s3 sync → CloudFront invalidation
```

Store in GitHub Secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `EIA_API_KEY`.

---

## Frontend (React)

Key components:
- `StateMap.jsx` — choropleth US map using `react-simple-maps`. Color scale: light yellow → dark red based on price. Clicking a state updates the chart below.
- `PriceChart.jsx` — Recharts `LineChart`. Shows price over time for selected state. Overlays national average as a dashed line.
- `PeriodToggle.jsx` — three-button toggle: Weekly / Monthly / Yearly. Changing period re-fetches from API.

API base URL: stored in `.env` as `VITE_API_BASE_URL`, set to the API Gateway invoke URL.

---

## Build order (phases)

Build in this exact order — each phase depends on the previous:

1. **Phase 1** — Terraform networking + storage + database modules. VPC, IGW, public/private subnets, S3 Gateway endpoint, Secrets Manager Interface endpoint, security groups, RDS PostgreSQL 15 (private subnet), S3 buckets. Upstash Redis provisioned manually on upstash.com. ✅ COMPLETE
2. **Phase 2** — Ingest Lambda (outside VPC). Fetches from EIA API with exponential backoff, validates with Pydantic v2, writes raw JSON to S3 `raw/YYYY/MM/DD/prices.json`. EventBridge weekly schedule `cron(0 14 ? * MON *)`. SQS DLQ for failed invocations. Versioned with `prod` alias. ✅ COMPLETE
3. **Phase 3** — Transform Lambda (VPC-attached, private subnet). Triggered by S3 `ObjectCreated` event on `raw/*.json`. Aggregates weekly → monthly → yearly. Upserts into RDS via SQLAlchemy. Redis invalidation removed (no internet route from VPC private subnet). Versioned with `prod` alias. ✅ COMPLETE
4. **Phase 4** — FastAPI API Lambda (VPC-attached, private subnet). All 6 endpoints, cache-aside pattern (Redis disabled — no NAT), typed error handlers, rate limit middleware, structured logging. Deployed behind API Gateway HTTP API v2. ✅ COMPLETE
5. **Phase 5** — Monitoring module. SNS topic + email subscription, 7 CloudWatch alarms (ingest errors, transform errors, API error rate >5%, DLQ depth, RDS CPU >80%, API p99 latency >3s, API Gateway 5xx). ✅ COMPLETE
6. **Phase 6** — React frontend. Choropleth map, line chart, period toggle. Deploy to S3 + CloudFront. ✅ COMPLETE
7. **Phase 7** — CI/CD. GitHub Actions workflows for infra and app deploys.

---

## Environment variables (injected by Terraform into Lambda)

| Variable | Description |
|---|---|
| `DB_HOST` | RDS endpoint |
| `DB_NAME` | `gas_prices` |
| `DB_USER` | from Secrets Manager |
| `DB_PASSWORD` | from Secrets Manager |
| `REDIS_URL` | Upstash Redis URL (`rediss://...`) — from Secrets Manager as `gas-price/redis-url` |
| `RAW_BUCKET` | S3 bucket name for raw data |
| `PROCESSED_BUCKET` | S3 bucket name for processed data |
| `EIA_API_KEY` | from Secrets Manager |
| `ENVIRONMENT` | `prod` or `dev` |

---

## Key constraints and decisions

- **Redis is Upstash, not ElastiCache** — accessed over HTTPS (`rediss://`), not a VPC-internal endpoint. URL stored in Secrets Manager as `gas-price-prod/redis-url`. Provision via upstash.com dashboard, not Terraform. Select region `us-east-1` to match AWS.
- **No NAT Gateway** — removed to save ~$33/mo. Internet access is handled differently per Lambda:
  - **Ingest Lambda** runs *outside* the VPC (no `vpc_config`). Reaches EIA API, S3, and Secrets Manager directly over the internet via IGW. Uses `AWSLambdaBasicExecutionRole`.
  - **Transform Lambda** runs *inside* the VPC (private subnet). Reaches S3 via a free Gateway VPC endpoint, Secrets Manager via an Interface VPC endpoint (~$7/mo), and RDS directly over the private network. Redis invalidation goes via HTTPS and is non-fatal.
  - **Important:** A Lambda attached to a VPC *never* gets a public IP, even in a public subnet — attaching to public subnets while dropping NAT simply breaks internet access. The correct solution is to either run outside the VPC (ingest) or use VPC endpoints (transform).
- **VPC endpoints deployed:**
  - S3 Gateway endpoint — free. Injects routes directly into the private route table.
  - Secrets Manager Interface endpoint — ~$7/mo. Creates ENIs in private subnets with private DNS enabled so Lambda resolves `secretsmanager.*.amazonaws.com` to the endpoint automatically.
- **RDS stays in private subnets** — only accessible from the Lambda security group on port 5432. No public access.
- **No ElastiCache** — removed entirely. Upstash free tier (10k commands/day, 256MB) is sufficient for this project's traffic.
- Lambda security group: egress 443 open to `0.0.0.0/0` (for HTTPS to Upstash + public AWS APIs), egress 5432 to RDS SG only. No broad egress needed for internet from VPC-attached Lambdas other than Redis.
- Lambda functions use IAM roles with least-privilege policies (no wildcard `*` actions)
- Redis cache failures must NEVER cause API errors — always fall through to RDS (wrap all Redis calls in try/except)
- Redis invalidation in transform Lambda uses SCAN+DEL on `prices:*` keys — non-fatal, logged as warning only
- EIA API state codes use their own format (e.g. `SCA` not `CA`) — strip the leading `S` prefix in transform; skip non-state codes (e.g. `R10` regional averages)
- Gas prices update weekly (Monday) — ETL schedule is `cron(0 14 ? * MON *)` (Monday 2pm UTC, after EIA publishes)
- Use `UPSERT` (INSERT ... ON CONFLICT DO UPDATE) in all DB writes — the backfill script will re-run safely
- Pydantic v2 syntax throughout (`model_config = ConfigDict(...)`, `field_validator`, `model_validator` — not v1 `@validator`)
- Lambda packaging: use `--platform manylinux2014_x86_64 --python-version 3.12 --implementation cp --only-binary=:all:` to build correct Linux wheels on any local OS
- Upstash Redis connection string format: `rediss://default:<password>@<host>.upstash.io:6379`
- Secrets Manager secret naming convention: `{project}-{environment}/{secret-name}` e.g. `gas-price-prod/eia-api-key`

## Estimated monthly cost

| Service | Cost |
|---|---|
| RDS Postgres db.t3.micro | ~$16/mo |
| Upstash Redis | $0 (free tier) |
| Lambda, S3, EventBridge, SQS | $0 (free tier) |
| API Gateway | ~$0.01 |
| CloudWatch alarms + logs | ~$1.00 |
| Secrets Manager (4 secrets: db-password, redis-url, eia-api-key + 1 future) | ~$1.60 |
| Secrets Manager VPC Interface endpoint (1 AZ) | ~$7.00 |
| CloudFront + S3 frontend | ~$0.50 |
| NAT Gateway | $0 (removed — saves ~$33/mo) |
| ElastiCache | $0 (removed — using Upstash free tier) |
| **Total** | **~$26/mo** |
