locals {
  name_prefix = "${var.project}-${var.environment}"
}

# ---------------------------------------------------------------------------
# Secrets Manager — RDS master password
# Lambda functions fetch this at runtime via the ARN output.
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${local.name_prefix}/db-password"
  description             = "RDS master password for the gas price dashboard."
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-db-password-secret" }
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = var.db_password
}

# ---------------------------------------------------------------------------
# RDS Subnet Group
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "main" {
  name        = "${local.name_prefix}-db-subnet-group"
  description = "Private subnets for RDS PostgreSQL."
  subnet_ids  = var.subnet_ids

  tags = { Name = "${local.name_prefix}-db-subnet-group" }
}

# ---------------------------------------------------------------------------
# RDS Parameter Group — PostgreSQL 15
# ---------------------------------------------------------------------------

resource "aws_db_parameter_group" "postgres15" {
  name        = "${local.name_prefix}-pg15"
  family      = "postgres15"
  description = "Custom parameter group for gas price dashboard PostgreSQL 15."

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  tags = { Name = "${local.name_prefix}-pg15-params" }
}

# ---------------------------------------------------------------------------
# IAM role for RDS Enhanced Monitoring
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "rds_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rds_enhanced_monitoring" {
  name               = "${local.name_prefix}-rds-monitoring-role"
  assume_role_policy = data.aws_iam_policy_document.rds_assume_role.json

  tags = { Name = "${local.name_prefix}-rds-monitoring-role" }
}

resource "aws_iam_role_policy_attachment" "rds_enhanced_monitoring" {
  role       = aws_iam_role.rds_enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ---------------------------------------------------------------------------
# RDS Instance — PostgreSQL 15
# ---------------------------------------------------------------------------

resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-postgres"

  engine         = "postgres"
  engine_version = "15"
  instance_class = var.rds_instance_class

  allocated_storage     = var.rds_allocated_storage
  max_allocated_storage = var.rds_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.rds_sg_id]
  publicly_accessible    = false
  multi_az               = false

  parameter_group_name = aws_db_parameter_group.postgres15.name
  ca_cert_identifier   = "rds-ca-rsa2048-g1"

  backup_retention_period  = var.rds_backup_retention_days
  backup_window            = "03:00-04:00"
  maintenance_window       = "Mon:04:00-Mon:05:00"
  copy_tags_to_snapshot    = true
  delete_automated_backups = false

  performance_insights_enabled          = true
  performance_insights_retention_period = 7
  monitoring_interval                   = 60
  monitoring_role_arn                   = aws_iam_role.rds_enhanced_monitoring.arn
  enabled_cloudwatch_logs_exports       = ["postgresql", "upgrade"]

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-final-snapshot"

  # Ignore password after initial creation — rotations happen via Secrets Manager
  lifecycle {
    ignore_changes = [password]
  }

  tags = { Name = "${local.name_prefix}-postgres" }
}

# ---------------------------------------------------------------------------
# Secrets Manager — Upstash Redis URL
# Stored here so Lambdas can fetch it at runtime the same way as the DB password.
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "redis_url" {
  name                    = "${local.name_prefix}/redis-url"
  description             = "Upstash Redis connection URL for the gas price dashboard."
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-redis-url-secret" }
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id     = aws_secretsmanager_secret.redis_url.id
  secret_string = var.redis_url
}
