output "rds_instance_id" {
  description = "RDS DB instance identifier — used as a CloudWatch dimension."
  value       = aws_db_instance.main.identifier
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint in host:port format."
  value       = aws_db_instance.main.endpoint
  sensitive   = true
}

output "rds_address" {
  description = "RDS hostname only (without port). Used as DB_HOST env var."
  value       = aws_db_instance.main.address
  sensitive   = true
}

output "rds_port" {
  description = "RDS port."
  value       = aws_db_instance.main.port
}

output "rds_db_name" {
  description = "PostgreSQL database name."
  value       = aws_db_instance.main.db_name
}

output "redis_endpoint" {
  description = "Upstash Redis connection URL (rediss://:password@host:port)."
  value       = var.redis_url
  sensitive   = true
}

output "redis_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the Upstash Redis URL."
  value       = aws_secretsmanager_secret.redis_url.arn
}

output "db_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the RDS master password."
  value       = aws_secretsmanager_secret.db_password.arn
}
