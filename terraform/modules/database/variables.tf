variable "project" {
  description = "Project name prefix."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for the DB subnet group."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for DB and cache subnet groups."
  type        = list(string)
}

variable "rds_sg_id" {
  description = "Security group ID to attach to the RDS instance."
  type        = string
}

variable "db_name" {
  description = "PostgreSQL database name."
  type        = string
}

variable "db_username" {
  description = "PostgreSQL master username."
  type        = string
}

variable "db_password" {
  description = "PostgreSQL master password (stored in Secrets Manager after creation)."
  type        = string
  sensitive   = true
}

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.micro"
}

variable "rds_allocated_storage" {
  description = "Allocated storage in GiB for RDS."
  type        = number
  default     = 20
}

variable "rds_max_allocated_storage" {
  description = "Maximum storage autoscaling ceiling in GiB."
  type        = number
  default     = 100
}

variable "rds_backup_retention_days" {
  description = "Number of days to retain automated backups."
  type        = number
  default     = 7
}

variable "redis_url" {
  description = "Upstash Redis connection URL (rediss://:password@host:port)."
  type        = string
  sensitive   = true
}
