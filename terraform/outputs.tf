# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

output "vpc_id" {
  description = "ID of the application VPC."
  value       = module.networking.vpc_id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets (used by Lambda, RDS, ElastiCache)."
  value       = module.networking.private_subnet_ids
}

output "public_subnet_ids" {
  description = "IDs of the public subnets (used by NAT gateway)."
  value       = module.networking.public_subnet_ids
}

output "lambda_sg_id" {
  description = "Security group ID assigned to Lambda functions."
  value       = module.networking.lambda_sg_id
}

output "rds_sg_id" {
  description = "Security group ID assigned to the RDS instance."
  value       = module.networking.rds_sg_id
}

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

output "raw_bucket_name" {
  description = "S3 bucket name for raw EIA API responses."
  value       = module.storage.raw_bucket_name
}

output "processed_bucket_name" {
  description = "S3 bucket name for transformed/aggregated data."
  value       = module.storage.processed_bucket_name
}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)."
  value       = module.database.rds_endpoint
  sensitive   = true
}

output "redis_endpoint" {
  description = "ElastiCache Redis endpoint for redis-py (rediss://host:port)."
  value       = module.database.redis_endpoint
  sensitive   = true
}

output "db_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the RDS password."
  value       = module.database.db_secret_arn
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Lambda (Phase 2)
# ---------------------------------------------------------------------------

output "ingest_function_name" {
  description = "Name of the EIA ingest Lambda function."
  value       = module.lambda.ingest_function_name
}

output "ingest_function_version" {
  description = "Lambda version number published by the most recent apply."
  value       = module.lambda.ingest_function_version
}

output "ingest_alias_arn" {
  description = "ARN of the ingest Lambda prod alias."
  value       = module.lambda.ingest_alias_arn
}

output "dlq_url" {
  description = "SQS DLQ URL — used by Phase 5 monitoring module."
  value       = module.lambda.dlq_url
}

# ---------------------------------------------------------------------------
# API Gateway (Phase 4)
# ---------------------------------------------------------------------------

output "api_invoke_url" {
  description = "Base URL for the API Gateway HTTP API. Set as VITE_API_BASE_URL in the frontend."
  value       = module.lambda.api_invoke_url
}

output "transform_function_name" {
  description = "Name of the transform Lambda function."
  value       = module.lambda.transform_function_name
}

output "api_function_name" {
  description = "Name of the FastAPI Lambda function."
  value       = module.lambda.api_function_name
}

# ---------------------------------------------------------------------------
# Monitoring (Phase 5)
# ---------------------------------------------------------------------------

output "sns_topic_arn" {
  description = "ARN of the SNS topic that receives all CloudWatch alarm notifications."
  value       = module.monitoring.sns_topic_arn
}

# ---------------------------------------------------------------------------
# Frontend (Phase 6)
# ---------------------------------------------------------------------------

output "frontend_bucket" {
  description = "S3 bucket holding the React build artefacts."
  value       = module.frontend.bucket_name
}

output "frontend_url" {
  description = "CloudFront URL for the dashboard (https://dXXX.cloudfront.net)."
  value       = "https://${module.frontend.cloudfront_domain}"
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID — used by CI/CD to invalidate cache after deploy."
  value       = module.frontend.cloudfront_distribution_id
}
