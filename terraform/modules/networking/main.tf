locals {
  name_prefix   = "${var.project}-${var.environment}"
  # Divide the /16 VPC into 4 equal /18s:
  #   10.0.0.0/18   public  AZ-a
  #   10.0.64.0/18  public  AZ-b
  #   10.0.128.0/18 private AZ-a
  #   10.0.192.0/18 private AZ-b
  public_cidrs  = [cidrsubnet(var.vpc_cidr, 2, 0), cidrsubnet(var.vpc_cidr, 2, 1)]
  private_cidrs = [cidrsubnet(var.vpc_cidr, 2, 2), cidrsubnet(var.vpc_cidr, 2, 3)]
}

# ---------------------------------------------------------------------------
# VPC
# ---------------------------------------------------------------------------

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true  # required for VPC endpoint private DNS to work

  tags = { Name = "${local.name_prefix}-vpc" }
}

# ---------------------------------------------------------------------------
# Internet Gateway (used by public subnets only)
# ---------------------------------------------------------------------------

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-igw" }
}

# ---------------------------------------------------------------------------
# Subnets
# ---------------------------------------------------------------------------

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = false

  tags = { Name = "${local.name_prefix}-public-${count.index + 1}" }
}

resource "aws_subnet" "private" {
  count = 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = { Name = "${local.name_prefix}-private-${count.index + 1}" }
}

# ---------------------------------------------------------------------------
# Route Tables
# ---------------------------------------------------------------------------

# Public route table — IGW for internet-bound traffic
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name_prefix}-rt-public" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private route table — local VPC routing only (no NAT gateway).
# Internet traffic from private subnets is dropped.
# AWS services (S3, Secrets Manager) are reached via VPC endpoints below.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-rt-private" }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ---------------------------------------------------------------------------
# VPC Endpoints — allow private subnets to reach AWS services without internet
# ---------------------------------------------------------------------------

# S3 Gateway endpoint — FREE. Routes S3 traffic within the AWS network.
# Used by the transform Lambda to read raw files without internet access.
# Gateway endpoints inject routes directly into the route table.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = { Name = "${local.name_prefix}-s3-endpoint" }
}

# Secrets Manager Interface endpoint — ~$7/mo.
# Used by the transform Lambda to fetch the DB password without internet access.
# Interface endpoints create an ENI inside the subnet with a private IP.
# private_dns_enabled means Lambda resolves secretsmanager.*.amazonaws.com
# to the endpoint IP automatically — no code changes needed.
resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = { Name = "${local.name_prefix}-secretsmanager-endpoint" }
}

data "aws_region" "current" {}

# ---------------------------------------------------------------------------
# Security Groups
# Created without inline rules to avoid circular references.
# ---------------------------------------------------------------------------

# Lambda functions (VPC-attached — transform, and future API Lambda)
resource "aws_security_group" "lambda" {
  name        = "${local.name_prefix}-lambda-sg"
  description = "Attached to all Lambda functions. Egress to RDS, Redis, and HTTPS."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-lambda-sg" }
}

# RDS PostgreSQL
resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "RDS PostgreSQL 15. Inbound 5432 from Lambda SG only."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-rds-sg" }
}

# VPC Interface endpoints (Secrets Manager)
resource "aws_security_group" "endpoints" {
  name        = "${local.name_prefix}-endpoints-sg"
  description = "VPC Interface endpoints. Inbound HTTPS from Lambda SG only."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name_prefix}-endpoints-sg" }

  lifecycle { create_before_destroy = true }
}

# ---------------------------------------------------------------------------
# Security Group Rules
# ---------------------------------------------------------------------------

# Lambda → VPC endpoints (Secrets Manager)
resource "aws_security_group_rule" "lambda_egress_https" {
  type              = "egress"
  description       = "HTTPS to VPC endpoints"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.lambda.id
}

# Lambda → RDS
resource "aws_security_group_rule" "lambda_egress_postgres" {
  type                     = "egress"
  description              = "PostgreSQL to RDS"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.rds.id
  security_group_id        = aws_security_group.lambda.id
}

# RDS ← Lambda
resource "aws_security_group_rule" "rds_ingress_lambda" {
  type                     = "ingress"
  description              = "PostgreSQL from Lambda"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.lambda.id
  security_group_id        = aws_security_group.rds.id
}

# Endpoints ← Lambda (Secrets Manager needs inbound 443 from Lambda)
resource "aws_security_group_rule" "endpoints_ingress_lambda" {
  type                     = "ingress"
  description              = "HTTPS from Lambda to VPC endpoints"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.lambda.id
  security_group_id        = aws_security_group.endpoints.id
}
