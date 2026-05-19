variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment label (prod or dev)."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["prod", "dev"], var.environment)
    error_message = "environment must be 'prod' or 'dev'."
  }
}

variable "project" {
  description = "Project name used as a prefix for all resource names and tags."
  type        = string
  default     = "gas-price"
}

variable "alert_email" {
  description = "Email address that receives CloudWatch SNS alerts (Phase 5)."
  type        = string
}

variable "db_name" {
  description = "PostgreSQL database name."
  type        = string
  default     = "gas_prices"
}

variable "db_username" {
  description = "PostgreSQL master username."
  type        = string
  default     = "gas_price_admin"
}

variable "db_password" {
  description = "PostgreSQL master password. Stored in Secrets Manager; passed here only at create time."
  type        = string
  sensitive   = true
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Two AZs to use for subnets. Must be in the chosen region."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "redis_url" {
  description = "Upstash Redis connection URL (rediss://:password@host:port)."
  type        = string
  sensitive   = true
}

variable "eia_api_key" {
  description = "EIA Open Data API key. Stored in Secrets Manager as gas-price-prod/eia-api-key."
  type        = string
  sensitive   = true
}
