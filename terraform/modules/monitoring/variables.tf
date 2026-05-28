variable "project" {
  description = "Project name prefix used for resource naming."
  type        = string
}

variable "environment" {
  description = "Deployment environment (prod or dev)."
  type        = string
}

variable "alert_email" {
  description = "Email address that receives all CloudWatch alarm notifications."
  type        = string
}

variable "ingest_function_name" {
  description = "Name of the ingest Lambda function."
  type        = string
}

variable "transform_function_name" {
  description = "Name of the transform Lambda function."
  type        = string
}

variable "api_function_name" {
  description = "Name of the API Lambda function."
  type        = string
}

variable "dlq_arn" {
  description = "ARN of the SQS Dead Letter Queue used by the ingest Lambda."
  type        = string
}

variable "rds_instance_id" {
  description = "RDS DB instance identifier (used as CloudWatch dimension)."
  type        = string
}

variable "api_gateway_id" {
  description = "API Gateway HTTP API ID (used as CloudWatch dimension for 5xx alarm)."
  type        = string
}

variable "cloudfront_domain" {
  description = "CloudFront distribution domain (e.g. dXXX.cloudfront.net). Used to scope the RUM app monitor to the correct origin."
  type        = string
}
