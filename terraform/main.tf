terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ---------------------------------------------------------------------------
# Phase 1 modules
# ---------------------------------------------------------------------------

module "networking" {
  source = "./modules/networking"

  project            = var.project
  environment        = var.environment
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
}

module "storage" {
  source = "./modules/storage"

  project     = var.project
  environment = var.environment
}

module "database" {
  source = "./modules/database"

  project     = var.project
  environment = var.environment

  vpc_id     = module.networking.vpc_id
  subnet_ids = module.networking.private_subnet_ids
  rds_sg_id  = module.networking.rds_sg_id

  db_name     = var.db_name
  db_username = var.db_username
  db_password = var.db_password

  redis_url = var.redis_url
}

# ---------------------------------------------------------------------------
# Phase 2 — Lambda (ingest)
# ---------------------------------------------------------------------------

module "lambda" {
  source = "./modules/lambda"

  project     = var.project
  environment = var.environment

  vpc_id       = module.networking.vpc_id
  subnet_ids   = module.networking.private_subnet_ids
  lambda_sg_id = module.networking.lambda_sg_id

  raw_bucket_name = module.storage.raw_bucket_name
  raw_bucket_arn  = module.storage.raw_bucket_arn

  eia_api_key = var.eia_api_key

  # Phase 3 — transform Lambda DB + Redis wiring
  db_host          = module.database.rds_address
  db_name          = module.database.rds_db_name
  db_username      = var.db_username
  db_secret_arn    = module.database.db_secret_arn
  redis_secret_arn = module.database.redis_secret_arn

  # OWASP API7 — CORS: pass the CloudFront URL so the API restricts
  # Access-Control-Allow-Origin to the known frontend origin only.
  frontend_origin = "https://${module.frontend.cloudfront_domain}"
}

# ---------------------------------------------------------------------------
# Phase 6 — Frontend (S3 + CloudFront)
# ---------------------------------------------------------------------------

module "frontend" {
  source = "./modules/frontend"

  project     = var.project
  environment = var.environment

  api_invoke_url = module.lambda.api_invoke_url
}

# ---------------------------------------------------------------------------
# Phase 5 — Monitoring (CloudWatch alarms + SNS email alerts)
# ---------------------------------------------------------------------------

module "monitoring" {
  source = "./modules/monitoring"

  project     = var.project
  environment = var.environment
  alert_email = var.alert_email

  ingest_function_name    = module.lambda.ingest_function_name
  transform_function_name = module.lambda.transform_function_name
  api_function_name       = module.lambda.api_function_name

  dlq_arn         = module.lambda.dlq_arn
  rds_instance_id = module.database.rds_instance_id
  api_gateway_id  = module.lambda.api_gateway_id
}
