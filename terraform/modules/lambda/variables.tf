variable "project" {
  description = "Project name prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment (prod or dev)."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID — passed to the Lambda VPC config."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for Lambda VPC attachment."
  type        = list(string)
}

variable "lambda_sg_id" {
  description = "Security group ID attached to all Lambda functions."
  type        = string
}

variable "raw_bucket_name" {
  description = "Name of the raw S3 bucket. Injected as RAW_BUCKET env var."
  type        = string
}

variable "raw_bucket_arn" {
  description = "ARN of the raw S3 bucket. Used in the Lambda IAM policy."
  type        = string
}

variable "eia_api_key" {
  description = "EIA Open Data API key. Stored in Secrets Manager by this module."
  type        = string
  sensitive   = true
}

variable "ingest_lambda_version" {
  description = "Lambda version the prod alias points to. Default tracks the latest published version. Set to a number (e.g. '3') to roll back."
  type        = string
  default     = "$LATEST"
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds."
  type        = number
  default     = 60
}

variable "lambda_memory_mb" {
  description = "Lambda memory allocation in MB."
  type        = number
  default     = 256
}

variable "log_retention_days" {
  description = "CloudWatch log group retention in days."
  type        = number
  default     = 14
}

# ---------------------------------------------------------------------------
# Phase 3 — transform Lambda DB + Redis wiring
# ---------------------------------------------------------------------------

variable "db_host" {
  description = "RDS hostname (without port). Injected as DB_HOST env var."
  type        = string
}

variable "db_name" {
  description = "PostgreSQL database name. Injected as DB_NAME env var."
  type        = string
}

variable "db_username" {
  description = "PostgreSQL master username. Injected as DB_USERNAME env var."
  type        = string
}

variable "db_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the RDS master password."
  type        = string
}

variable "redis_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the Upstash Redis URL."
  type        = string
}
