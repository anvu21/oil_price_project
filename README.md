# US Gas Price Dashboard

A full-stack, AWS-native web application that visualises weekly retail gasoline prices across all 50 US states + DC. Click any state on the choropleth map to drill into its weekly, monthly, or yearly price history alongside the national average.

**Live demo:** https://d29v5i05cdp0sg.cloudfront.net  
**API base:** https://x4ybqkzbf1.execute-api.us-east-1.amazonaws.com

---

## Features

- **Interactive choropleth map** — all 51 states coloured by price (blue = cheap, red = expensive)
- **State drill-down** — click any state to see its full price history as a line chart
- **Period toggle** — switch between Weekly / Monthly / Yearly aggregations
- **National average overlay** — dashed line on every chart for easy comparison
- **PADD regional fallback** — the EIA only publishes individual data for 9 states; the remaining 42 use their PADD (Petroleum Administration for Defense Districts) regional average so the map is always fully populated
- **Redis cache** — all API responses cached for 1 hour; cache-aside pattern with silent fallback to RDS on cache miss
- **Fully automated ETL** — EventBridge triggers the ingest Lambda every Monday after EIA publishes; data flows S3 → transform Lambda → RDS automatically

---

## Tech stack

| Layer | Technology |
|---|---|
| ETL | Python 3.12, Pydantic v2, AWS Lambda |
| API | FastAPI, Mangum (ASGI → Lambda adapter) |
| Database | AWS RDS PostgreSQL 15 (prod) / Docker PostgreSQL 15 (local) |
| Cache | Upstash Redis (prod) / Docker Redis 7 (local) |
| Scheduling | AWS EventBridge (weekly cron) |
| Failure handling | AWS SQS Dead Letter Queue |
| Object storage | AWS S3 (raw + processed data) |
| API layer | AWS API Gateway (HTTP API v2) |
| Observability | AWS CloudWatch (logs, alarms, dashboards) |
| Alerting | AWS SNS (email) |
| IaC | Terraform >= 1.7 (modularised) |
| Frontend | React 18, Recharts, Tailwind CSS, react-simple-maps |
| Frontend hosting | AWS S3 + CloudFront |

---

## Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                    AWS                              │
                    │                                                     │
  EventBridge ──────► Lambda: ingest ──────────────► EIA Open Data API   │
  (Mon 2pm UTC)     │  (outside VPC)  └──► S3 raw/  (internet)          │
                    │                      │                             │
                    │              S3 ObjectCreated                      │
                    │                      │                             │
                    │                      ▼                             │
                    │           Lambda: transform ──► RDS PostgreSQL     │
                    │             (private subnet)    (private subnet)   │
                    │                      └──► Redis invalidation       │
                    │                           (Upstash, HTTPS)        │
                    │                                                     │
  Browser ──────────► CloudFront ──► S3 (static React build)            │
           └─────────► API Gateway ──► Lambda: FastAPI ──► Redis         │
                    │                   (private subnet)  └──► RDS      │
                    │                                                     │
                    │  CloudWatch alarms ──► SNS ──► email               │
                    └─────────────────────────────────────────────────────┘
```

### Key networking decisions

Lambda functions attached to a VPC never get a public IP — they need a NAT Gateway (~$33/mo) to reach the internet. To avoid that cost:

- **Ingest Lambda** runs *outside* the VPC — reaches EIA API, S3, and Secrets Manager directly over the internet
- **Transform Lambda** runs *inside* the VPC (private subnet) — reaches S3 via free Gateway VPC endpoint, Secrets Manager via Interface endpoint (~$7/mo), RDS directly over the private network
- **API Lambda** runs *inside* the VPC — reaches RDS directly; Upstash Redis is reached over HTTPS (non-fatal if unavailable)

---

## Running locally with Docker

The entire stack — Postgres, Redis, FastAPI, and the React frontend — runs in Docker. No Python, Node, or AWS credentials are needed.

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- A free [EIA API key](https://www.eia.gov/opendata/) — registration takes about 30 seconds and is required to seed real price data

### Step 1 — Configure environment

Copy the example env file and add your EIA API key:

```bash
cp .env.example .env
```

Edit `.env`:

```
EIA_API_KEY=your_eia_api_key_here
```

That's the only required change. All other values (Postgres credentials, ports, etc.) are pre-filled with local defaults.

### Step 2 — Start all services

```bash
git clone <repo-url>
cd gas-price-dashboard
docker compose up --build
```

The first run pulls Docker images and installs npm packages — allow about 2–3 minutes. Subsequent starts are fast (a few seconds).

Once running, the following are available:

| Service | URL | Notes |
|---|---|---|
| React frontend | http://localhost:3000 | Vite dev server with hot module reload |
| FastAPI | http://localhost:8000 | uvicorn with `--reload` |
| Swagger UI | http://localhost:8000/docs | Interactive API explorer |
| ReDoc | http://localhost:8000/redoc | Alternate API docs |
| Health check | http://localhost:8000/v1/health | DB + cache connectivity status |
| PostgreSQL | localhost:5432 | user: `gas_price_admin` / pw: `localpassword` |
| Redis | localhost:6379 | no auth |

### Step 3 — Seed the database

The schema is created automatically on first start, but no price data exists yet. Run the backfill script to fetch up to 3 years of weekly prices from the EIA API:

```bash
docker compose exec api python /scripts/backfill.py
```

The `EIA_API_KEY` from `.env` is automatically injected into the container — no extra flags needed. The script fetches ~2,500 rows (9 individual state series + 7 PADD regional series) and takes about 30–60 seconds.

```
Backfill: fetching 3 year(s) of EIA data from 2023-05-19
Database: gas_price_admin@postgres:5432/gas_prices

Connecting to database…
Fetching from EIA API…
  upserted 2,496 weekly rows so far…
  fetched 4,524 / 4,524 rows from EIA

  weekly rows upserted : 2,496
  rows skipped (non-state / null) : 2,028

Recomputing monthly rollup…  monthly rows upserted: 592
Recomputing yearly rollup…   yearly rows upserted : 64

Done.
```

> **Windows (Git Bash only):** Git Bash rewrites paths that start with `/`. Prefix with `MSYS_NO_PATHCONV=1` to prevent this:
> ```bash
> MSYS_NO_PATHCONV=1 docker compose exec api python /scripts/backfill.py
> ```
> PowerShell and CMD do not have this issue.

To fetch more history:

```bash
docker compose exec api python /scripts/backfill.py --years 5
```

Open http://localhost:3000 — the map should now be fully coloured.

### Step 4 — Make changes

Source files are bind-mounted into the containers, so edits take effect without restarting:

- **Frontend** (`frontend/src/`) — Vite HMR pushes changes to the browser instantly
- **API** (`lambdas/api/`) — uvicorn `--reload` restarts the server on every file save

### Step 5 — Stop

```bash
docker compose down       # stop containers; Postgres data is preserved
docker compose down -v    # stop containers AND delete all data (fresh start)
```

---

## Project structure

```
gas-price-dashboard/
│
├── .env.example                     # template — copy to .env and fill in EIA_API_KEY
├── docker-compose.yml               # local dev: Postgres, Redis, FastAPI, React
│
├── scripts/
│   ├── init_db.sql                  # schema DDL (auto-run by Docker Postgres on first start)
│   ├── backfill.py                  # fetch historical EIA data → local DB
│   └── package_lambda.py            # zip Lambda functions for AWS deploy
│
├── lambdas/
│   ├── ingest/                      # Lambda 1: EIA API → S3
│   │   ├── handler.py               # Lambda entry point
│   │   ├── eia_client.py            # EIA API pagination + retry logic
│   │   ├── models.py                # Pydantic input validation
│   │   └── requirements.txt
│   │
│   ├── transform/                   # Lambda 2: S3 → RDS
│   │   ├── handler.py               # Lambda entry point (triggered by S3 ObjectCreated)
│   │   ├── aggregator.py            # weekly → monthly + yearly rollups
│   │   ├── models.py
│   │   └── requirements.txt
│   │
│   └── api/                         # Lambda 3: FastAPI behind API Gateway
│       ├── handler.py               # Mangum ASGI adapter (Lambda entry point)
│       ├── main.py                  # FastAPI app, CORS, middleware
│       ├── routers/
│       │   └── prices.py            # all price endpoints + PADD fallback logic
│       ├── models.py                # Pydantic response models
│       ├── db.py                    # SQLAlchemy engine, session factory
│       ├── cache.py                 # Redis cache-aside helpers
│       ├── exceptions.py            # typed exception handlers
│       ├── requirements.txt
│       └── Dockerfile               # local: uvicorn dev server
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx                  # two-view app (map view ↔ state detail view)
│   │   ├── components/
│   │   │   ├── StateMap.jsx         # choropleth map (react-simple-maps + d3-scale)
│   │   │   ├── PriceChart.jsx       # line chart (Recharts)
│   │   │   └── PeriodToggle.jsx     # Weekly / Monthly / Yearly toggle
│   │   └── api/
│   │       └── client.js            # fetch wrappers for all API endpoints
│   ├── Dockerfile                   # local: Vite dev server
│   └── package.json
│
└── terraform/
    ├── main.tf                      # top-level module wiring
    ├── variables.tf
    ├── outputs.tf
    ├── backend.tf                   # S3 remote state + DynamoDB lock
    └── modules/
        ├── networking/              # VPC, subnets, security groups, VPC endpoints
        ├── storage/                 # S3 buckets (raw, processed, frontend)
        ├── database/                # RDS PostgreSQL 15 + Secrets Manager secrets
        ├── lambda/                  # all three Lambdas, API Gateway, EventBridge, SQS DLQ
        ├── monitoring/              # CloudWatch alarms + SNS email alerts
        └── frontend/                # CloudFront distribution + OAC
```

---

## Data source

The [EIA Open Data API](https://www.eia.gov/opendata/) provides free weekly retail gasoline prices. Registration is required but takes about 30 seconds.

**Endpoint:** `https://api.eia.gov/v2/petroleum/pri/gnd/data/`

**Key query parameters:**

| Parameter | Value | Meaning |
|---|---|---|
| `frequency` | `weekly` | Weekly observations |
| `facets[product][]` | `EPM0` | Regular gasoline |
| `facets[process][]` | `PTE` | Retail price |
| `data[]` | `value` | Include the price value |

### PADD regional fallback

The EIA only publishes individual state-level series for **9 states**: CA, CO, FL, MA, MN, NY, OH, TX, WA. The remaining 42 states use their [PADD regional average](https://www.eia.gov/tools/glossary/index.php?id=petroleum+administration+for+defense+district):

| PADD Code | Region | States |
|---|---|---|
| R1X | New England (PADD 1A) | CT, ME, NH, RI, VT |
| R1Y | Central Atlantic (PADD 1B) | DC, DE, MD, NJ, PA |
| R1Z | Lower Atlantic (PADD 1C) | GA, NC, SC, VA, WV |
| R20 | Midwest (PADD 2) | IL, IN, IA, KS, KY, MI, MO, NE, ND, OK, SD, TN, WI |
| R30 | Gulf Coast (PADD 3) | AL, AR, LA, MS, NM |
| R40 | Rocky Mountain (PADD 4) | ID, MT, UT, WY |
| R50 | West Coast (PADD 5) | AK, AZ, HI, NV, OR |

The API returns `"source": "region"` and a `region_name` (e.g. `"Rocky Mountain (PADD 4)"`) for PADD-backed states. The frontend shows an amber badge in the state detail view and tooltip when regional data is being used.

---

## Database schema

```sql
-- Weekly prices — one row per state/PADD-region per week
-- state is a 2-char abbreviation (e.g. 'CA') for individual states
-- or a 3-char PADD code (e.g. 'R20') for regional fallback data
CREATE TABLE prices_weekly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(10)   NOT NULL,
    week_start  DATE          NOT NULL,
    avg_price   NUMERIC(5,3)  NOT NULL,
    grade       VARCHAR(20)   NOT NULL DEFAULT 'regular',
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (state, week_start, grade)
);

-- Monthly rollup — aggregated by transform Lambda after each ingest
CREATE TABLE prices_monthly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(10)   NOT NULL,
    year_month  DATE          NOT NULL,   -- always the 1st of the month
    avg_price   NUMERIC(5,3)  NOT NULL,
    min_price   NUMERIC(5,3)  NOT NULL,
    max_price   NUMERIC(5,3)  NOT NULL,
    grade       VARCHAR(20)   NOT NULL DEFAULT 'regular',
    UNIQUE (state, year_month, grade)
);

-- Yearly rollup
CREATE TABLE prices_yearly (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state       VARCHAR(10)   NOT NULL,
    year        SMALLINT      NOT NULL,
    avg_price   NUMERIC(5,3)  NOT NULL,
    min_price   NUMERIC(5,3)  NOT NULL,
    max_price   NUMERIC(5,3)  NOT NULL,
    grade       VARCHAR(20)   NOT NULL DEFAULT 'regular',
    UNIQUE (state, year, grade)
);

-- ETL audit log — one row per Lambda invocation
CREATE TABLE ingest_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    status           VARCHAR(20) NOT NULL,   -- success / failed / partial
    records_fetched  INT,
    error_message    TEXT,
    s3_path          TEXT
);
```

All writes use `INSERT ... ON CONFLICT DO UPDATE` (upsert) so the backfill script and the weekly Lambda can both be run multiple times safely.

---

## API endpoints

All endpoints live under `/v1/`. Base URLs:

- **Local:** `http://localhost:8000/v1/`
- **Production:** `https://x4ybqkzbf1.execute-api.us-east-1.amazonaws.com/v1/`

Interactive docs are available at `/docs` (Swagger UI) and `/redoc` when running locally.

### `GET /v1/prices/latest`

Returns the most recent week's price for every state and DC. Used to populate the choropleth map.

```json
{
  "week_start": "2026-05-11",
  "data": [
    { "state": "CA", "avg_price": 6.087, "week_start": "2026-05-11", "source": "state" },
    { "state": "UT", "avg_price": 4.505, "week_start": "2026-05-11", "source": "region" },
    ...
  ]
}
```

### `GET /v1/prices/{state}`

Price history for a single state. Falls back to PADD regional data if no individual series exists.

| Query param | Default | Options |
|---|---|---|
| `period` | `weekly` | `weekly`, `monthly`, `yearly` |
| `grade` | `regular` | `regular`, `midgrade`, `premium`, `diesel` |
| `from` | — | `YYYY-MM-DD` start date |
| `to` | — | `YYYY-MM-DD` end date |

```json
{
  "state": "UT",
  "period": "weekly",
  "grade": "regular",
  "source": "region",
  "region_name": "Rocky Mountain (PADD 4)",
  "data": [
    { "date": "2023-05-22", "avg_price": 3.699 },
    { "date": "2023-05-29", "avg_price": 3.743 },
    ...
  ]
}
```

### `GET /v1/prices/national`

National average (mean across all individual-state rows) for the requested period.

| Query param | Default | Options |
|---|---|---|
| `period` | `weekly` | `weekly`, `monthly`, `yearly` |
| `grade` | `regular` | `regular`, `midgrade`, `premium`, `diesel` |

```json
{
  "period": "weekly",
  "grade": "regular",
  "data": [
    { "date": "2023-05-22", "avg_price": 3.572 },
    ...
  ]
}
```

### `GET /v1/prices/compare`

Side-by-side price series for multiple states in one request.

```
GET /v1/prices/compare?states=CA,TX,FL&period=weekly
```

```json
{
  "period": "weekly",
  "grade": "regular",
  "states": {
    "CA": [{ "date": "2023-05-22", "avg_price": 4.713 }, ...],
    "TX": [{ "date": "2023-05-22", "avg_price": 3.249 }, ...],
    "FL": [{ "date": "2023-05-22", "avg_price": 3.524 }, ...]
  }
}
```

### `GET /v1/states`

List of all 51 states with name, abbreviation, and EIA area code. Cached for 24 hours.

### `GET /v1/health`

Real-time connectivity check — never cached. Used as a CloudWatch alarm source.

```json
{
  "status": "healthy",
  "db_connected": true,
  "cache_connected": true,
  "last_ingest_at": "2026-05-12T14:03:22+00:00",
  "last_ingest_status": "success"
}
```

Status values: `healthy` (DB + cache up), `degraded` (DB up, cache down — API still serves), `unhealthy` (DB down).

---

## Deploying to AWS

### Prerequisites

- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) configured with your credentials (`aws configure`)
- [Terraform](https://developer.hashicorp.com/terraform/downloads) >= 1.7
- Python 3.12
- Node 20

### Step 1 — Bootstrap Terraform remote state (first time only)

Terraform state is stored in S3 with a DynamoDB lock table. Create both before the first apply:

```bash
aws s3 mb s3://gas-price-tf-state --region us-east-1

aws dynamodb create-table \
  --table-name gas-price-tf-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

### Step 2 — Provision Upstash Redis

The project uses [Upstash](https://upstash.com/) serverless Redis instead of ElastiCache (free tier is sufficient). Create a database manually:

1. Sign up at https://upstash.com/
2. Create a new Redis database → region: **us-east-1** → type: **Regional**
3. Copy the connection string — it looks like `rediss://default:<password>@<host>.upstash.io:6379`

### Step 3 — Create `terraform/secrets.tfvars`

This file is gitignored. Never commit it.

```hcl
db_password = "YourStrongPassword123!"
redis_url   = "rediss://default:<password>@<host>.upstash.io:6379"
eia_api_key = "your-eia-api-key"
alert_email = "you@example.com"
```

### Step 4 — Deploy infrastructure

```bash
python scripts/package_lambda.py   # zip all three Lambdas

cd terraform
terraform init
terraform plan -var-file=secrets.tfvars   # review what will be created
terraform apply -var-file=secrets.tfvars
```

First apply takes about 10–15 minutes (RDS provisioning is the slowest part).

### Step 5 — Seed the production database

After the infrastructure is up, run the backfill once against RDS to load historical data. Get the RDS endpoint from Terraform output:

```bash
terraform output rds_endpoint
```

Then run from your local machine (with the RDS security group allowing your IP, or from a bastion):

```bash
python scripts/backfill.py \
  --api-key your-eia-api-key \
  --db-host <rds-endpoint> \
  --db-username gas_price_admin \
  --db-password YourStrongPassword123! \
  --years 3
```

After the first seed, the weekly EventBridge cron (`cron(0 14 ? * MON *)`) handles all future updates automatically.

### Step 6 — Deploy the frontend

```bash
# Get outputs from Terraform
cd terraform
BUCKET=$(terraform output -raw frontend_bucket)
DISTRIBUTION=$(terraform output -raw cloudfront_distribution_id)
API_URL=$(terraform output -raw api_invoke_url)

# Build with the production API URL
cd ../frontend
VITE_API_BASE_URL=$API_URL npm run build

# Sync to S3 and invalidate CloudFront cache
aws s3 sync dist/ s3://$BUCKET --delete
aws cloudfront create-invalidation --distribution-id $DISTRIBUTION --paths "/*"
```

The live URL is:

```bash
terraform output frontend_url
```

### Rolling back a bad deploy

Lambda versions are published on every deploy and a `prod` alias points to the live version. To roll back:

```bash
# List recent versions
aws lambda list-versions-by-function --function-name gas-price-api --query 'Versions[*].[Version,LastModified]' --output table

# Point the alias to the previous version
aws lambda update-alias --function-name gas-price-api --name prod --function-version <previous-version>
```

Or set `api_lambda_version` in `terraform.tfvars` and run `terraform apply`.

---

## Monitoring & alerting

CloudWatch alarms are configured for all critical signals. Email alerts go to the address in `secrets.tfvars`.

| Alarm | Threshold | What it means |
|---|---|---|
| Ingest Lambda errors | > 0 in 5 min | Weekly EIA fetch failed |
| Transform Lambda errors | > 0 in 5 min | RDS write failed |
| API error rate | > 5% over 5 min | Elevated 5xx responses |
| SQS DLQ depth | > 0 | Ingest failed after all retries |
| RDS CPU | > 80% for 10 min | Database under unusual load |
| API p99 latency | > 3000ms | Slow responses (likely cache miss storm) |
| API Gateway 5xx | > 0 in 5 min | Gateway-level errors |

Check current alarm status:

```bash
aws cloudwatch describe-alarms --alarm-name-prefix gas-price --query 'MetricAlarms[*].[AlarmName,StateValue]' --output table
```

---

## Estimated monthly cost

| Service | Cost |
|---|---|
| RDS PostgreSQL db.t3.micro | ~$16.00 |
| Secrets Manager Interface VPC endpoint (1 AZ) | ~$7.00 |
| Secrets Manager (4 secrets × $0.40) | ~$1.60 |
| CloudWatch alarms + logs | ~$1.00 |
| CloudFront + S3 frontend | ~$0.50 |
| API Gateway (HTTP API) | ~$0.01 |
| Lambda, S3, EventBridge, SQS | $0.00 (free tier) |
| Upstash Redis | $0.00 (free tier — 10k commands/day) |
| NAT Gateway | $0.00 (removed — see architecture notes) |
| ElastiCache | $0.00 (replaced by Upstash) |
| **Total** | **~$26/mo** |

The biggest savings come from eliminating the NAT Gateway (~$33/mo) and ElastiCache (~$16/mo) by restructuring Lambda VPC placement and using Upstash's serverless Redis.

---

## Environment variables reference

### Local (docker-compose / `.env`)

| Variable | Default | Description |
|---|---|---|
| `EIA_API_KEY` | *(required)* | EIA Open Data API key — used by backfill script |
| `POSTGRES_DB` | `gas_prices` | Database name |
| `POSTGRES_USER` | `gas_price_admin` | Database user |
| `POSTGRES_PASSWORD` | `localpassword` | Database password |

### API Lambda (injected by Terraform)

| Variable | Description |
|---|---|
| `ENVIRONMENT` | `local` or `prod` — controls SSL mode and pool size |
| `DB_HOST` | RDS endpoint |
| `DB_NAME` | Database name |
| `DB_USERNAME` | Database user |
| `DB_PASSWORD` | Set directly in local dev; fetched from Secrets Manager in prod via `DB_SECRET_ARN` |
| `DB_SECRET_ARN` | Secrets Manager ARN for the DB password (prod only) |
| `REDIS_URL` | Direct Redis URL — used in local dev |
| `REDIS_SECRET_ARN` | Secrets Manager ARN for the Upstash Redis URL (prod only) |
| `REDIS_ENABLED` | `true` / `false` — set to `false` in prod API Lambda (no internet route from VPC) |
| `EIA_API_KEY` | Passed through to the container in local dev for the backfill script |
