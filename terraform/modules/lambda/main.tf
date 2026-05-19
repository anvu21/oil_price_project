locals {
  name_prefix = "${var.project}-${var.environment}"
}

# ---------------------------------------------------------------------------
# Secrets Manager — EIA API key
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "eia_api_key" {
  name                    = "${local.name_prefix}/eia-api-key"
  description             = "EIA Open Data API key for the gas price ingest Lambda."
  recovery_window_in_days = 7

  tags = { Name = "${local.name_prefix}-eia-api-key-secret" }
}

resource "aws_secretsmanager_secret_version" "eia_api_key" {
  secret_id     = aws_secretsmanager_secret.eia_api_key.id
  secret_string = var.eia_api_key
}

# ---------------------------------------------------------------------------
# SQS Dead Letter Queue
# Receives failed EventBridge → Lambda invocations after all retries.
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "ingest_dlq" {
  name                       = "${local.name_prefix}-ingest-dlq"
  message_retention_seconds  = 1209600 # 14 days (maximum)
  receive_wait_time_seconds  = 20      # long polling
  visibility_timeout_seconds = 300

  tags = { Name = "${local.name_prefix}-ingest-dlq" }
}

# ---------------------------------------------------------------------------
# IAM — Lambda execution role
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    sid     = "LambdaAssumeRole"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest_lambda" {
  name               = "${local.name_prefix}-ingest-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = { Name = "${local.name_prefix}-ingest-lambda-role" }
}

# Basic execution policy: CloudWatch Logs only.
# Ingest Lambda runs outside the VPC so it does not need VPC network interface permissions.
resource "aws_iam_role_policy_attachment" "ingest_basic_execution" {
  role       = aws_iam_role.ingest_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Inline policy: least-privilege access to S3, Secrets Manager, SQS DLQ
data "aws_iam_policy_document" "ingest_inline" {
  statement {
    sid       = "S3PutRaw"
    actions   = ["s3:PutObject"]
    resources = ["${var.raw_bucket_arn}/raw/*"]
  }

  statement {
    sid       = "SecretsManagerGetEIAKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.eia_api_key.arn]
  }

  statement {
    sid       = "SQSSendDLQ"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.ingest_dlq.arn]
  }
}

resource "aws_iam_role_policy" "ingest_inline" {
  name   = "${local.name_prefix}-ingest-inline-policy"
  role   = aws_iam_role.ingest_lambda.id
  policy = data.aws_iam_policy_document.ingest_inline.json
}

# ---------------------------------------------------------------------------
# CloudWatch Log Group — created explicitly to set retention
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${local.name_prefix}-ingest"
  retention_in_days = var.log_retention_days

  tags = { Name = "${local.name_prefix}-ingest-logs" }
}

# ---------------------------------------------------------------------------
# Lambda function
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "ingest" {
  function_name = "${local.name_prefix}-ingest"
  description   = "Fetches weekly gas prices from EIA API and writes raw JSON to S3."

  filename         = "${path.module}/../../../lambdas/ingest/ingest.zip"
  source_code_hash = filebase64sha256("${path.module}/../../../lambdas/ingest/ingest.zip")

  runtime = "python3.12"
  handler = "handler.handler"

  role    = aws_iam_role.ingest_lambda.arn
  publish = true # creates a new numbered version on every apply — enables rollback

  timeout     = var.lambda_timeout
  memory_size = var.lambda_memory_mb

  # No VPC config — ingest Lambda runs outside the VPC so it can reach the
  # EIA API directly over the internet. It does not need RDS access.
  # (VPC-attached Lambdas require a NAT Gateway for internet egress, which
  # we removed. Only transform + API Lambdas need VPC for RDS access.)

  environment {
    variables = {
      ENVIRONMENT     = var.environment
      RAW_BUCKET      = var.raw_bucket_name
      EIA_SECRET_NAME = aws_secretsmanager_secret.eia_api_key.name
    }
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.ingest_dlq.arn
  }

  depends_on = [
    aws_cloudwatch_log_group.ingest,
    aws_iam_role_policy.ingest_inline,
  ]

  tags = { Name = "${local.name_prefix}-ingest" }
}

# ---------------------------------------------------------------------------
# Lambda alias — prod
# Tracks the latest published version by default.
# To roll back: set ingest_lambda_version = "2" in secrets.tfvars and re-apply.
# ---------------------------------------------------------------------------

resource "aws_lambda_alias" "ingest_prod" {
  name             = "prod"
  description      = "Production alias — points to the live ingest Lambda version."
  function_name    = aws_lambda_function.ingest.arn
  function_version = var.ingest_lambda_version == "$LATEST" ? aws_lambda_function.ingest.version : var.ingest_lambda_version
}

# ---------------------------------------------------------------------------
# EventBridge — weekly schedule (Monday 14:00 UTC)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "ingest_schedule" {
  name                = "${local.name_prefix}-ingest-schedule"
  description         = "Triggers the EIA ingest Lambda every Monday at 14:00 UTC."
  schedule_expression = "cron(0 14 ? * MON *)"
  state               = "ENABLED"

  tags = { Name = "${local.name_prefix}-ingest-schedule" }
}

resource "aws_cloudwatch_event_target" "ingest_lambda" {
  rule      = aws_cloudwatch_event_rule.ingest_schedule.name
  target_id = "ingest-lambda-target"
  arn       = aws_lambda_alias.ingest_prod.arn
}

resource "aws_lambda_permission" "eventbridge_invoke" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ingest_schedule.arn
  qualifier     = aws_lambda_alias.ingest_prod.name
}

# ---------------------------------------------------------------------------
# Transform Lambda — IAM role
# ---------------------------------------------------------------------------

resource "aws_iam_role" "transform_lambda" {
  name               = "${local.name_prefix}-transform-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = { Name = "${local.name_prefix}-transform-lambda-role" }
}

resource "aws_iam_role_policy_attachment" "transform_vpc_execution" {
  role       = aws_iam_role.transform_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "transform_inline" {
  statement {
    sid       = "S3GetRaw"
    actions   = ["s3:GetObject"]
    resources = ["${var.raw_bucket_arn}/raw/*"]
  }

  statement {
    sid       = "SecretsManagerGetDbAndRedis"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_secret_arn, var.redis_secret_arn]
  }
}

resource "aws_iam_role_policy" "transform_inline" {
  name   = "${local.name_prefix}-transform-inline-policy"
  role   = aws_iam_role.transform_lambda.id
  policy = data.aws_iam_policy_document.transform_inline.json
}

# ---------------------------------------------------------------------------
# Transform Lambda — CloudWatch log group
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "transform" {
  name              = "/aws/lambda/${local.name_prefix}-transform"
  retention_in_days = var.log_retention_days

  tags = { Name = "${local.name_prefix}-transform-logs" }
}

# ---------------------------------------------------------------------------
# Transform Lambda — function
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "transform" {
  function_name = "${local.name_prefix}-transform"
  description   = "Reads raw EIA JSON from S3, upserts into RDS, invalidates Redis cache."

  filename         = "${path.module}/../../../lambdas/transform/transform.zip"
  source_code_hash = filebase64sha256("${path.module}/../../../lambdas/transform/transform.zip")

  runtime = "python3.12"
  handler = "handler.handler"

  role    = aws_iam_role.transform_lambda.arn
  publish = true

  timeout     = 120 # DB + Redis operations need more headroom than ingest
  memory_size = 256

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.lambda_sg_id]
  }

  environment {
    variables = {
      ENVIRONMENT      = var.environment
      DB_HOST          = var.db_host
      DB_NAME          = var.db_name
      DB_USERNAME      = var.db_username
      DB_PORT          = "5432"
      DB_SECRET_ARN    = var.db_secret_arn
      REDIS_SECRET_ARN = var.redis_secret_arn
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.transform,
    aws_iam_role_policy_attachment.transform_vpc_execution,
    aws_iam_role_policy.transform_inline,
  ]

  tags = { Name = "${local.name_prefix}-transform" }
}

resource "aws_lambda_alias" "transform_prod" {
  name             = "prod"
  description      = "Production alias — points to the live transform Lambda version."
  function_name    = aws_lambda_function.transform.arn
  function_version = aws_lambda_function.transform.version
}

# ---------------------------------------------------------------------------
# S3 event notification → transform Lambda
# The permission must exist before the notification is configured, otherwise
# S3 returns AccessDenied when trying to register the event source.
# ---------------------------------------------------------------------------

resource "aws_lambda_permission" "s3_invoke_transform" {
  statement_id  = "AllowS3InvokeTransform"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.transform.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.raw_bucket_arn
  qualifier     = aws_lambda_alias.transform_prod.name
}

resource "aws_s3_bucket_notification" "raw_to_transform" {
  bucket = var.raw_bucket_name

  lambda_function {
    lambda_function_arn = aws_lambda_alias.transform_prod.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"
    filter_suffix       = ".json"
  }

  depends_on = [aws_lambda_permission.s3_invoke_transform]
}

# ---------------------------------------------------------------------------
# API Lambda — IAM role
# Runs inside the VPC (private subnet) for direct RDS access.
# Redis (Upstash, external) is unreachable from the VPC without NAT —
# the API gracefully degrades to always querying RDS (cache-aside pattern
# is implemented correctly for when NAT is added).
# ---------------------------------------------------------------------------

resource "aws_iam_role" "api_lambda" {
  name               = "${local.name_prefix}-api-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = { Name = "${local.name_prefix}-api-lambda-role" }
}

# VPC access execution role: CloudWatch Logs + ENI management for VPC attachment
resource "aws_iam_role_policy_attachment" "api_vpc_execution" {
  role       = aws_iam_role.api_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "api_inline" {
  statement {
    sid     = "SecretsManagerGetDbAndRedis"
    actions = ["secretsmanager:GetSecretValue"]
    # DB password + Redis URL — fetched via the Secrets Manager VPC Interface endpoint
    resources = [var.db_secret_arn, var.redis_secret_arn]
  }
}

resource "aws_iam_role_policy" "api_inline" {
  name   = "${local.name_prefix}-api-inline-policy"
  role   = aws_iam_role.api_lambda.id
  policy = data.aws_iam_policy_document.api_inline.json
}

# ---------------------------------------------------------------------------
# API Lambda — CloudWatch log group
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name_prefix}-api"
  retention_in_days = var.log_retention_days

  tags = { Name = "${local.name_prefix}-api-logs" }
}

# ---------------------------------------------------------------------------
# API Lambda — function
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "api" {
  function_name = "${local.name_prefix}-api"
  description   = "FastAPI backend for the gas price dashboard, served via Mangum + API Gateway."

  filename         = "${path.module}/../../../lambdas/api/api.zip"
  source_code_hash = filebase64sha256("${path.module}/../../../lambdas/api/api.zip")

  runtime = "python3.12"
  handler = "handler.handler"

  role    = aws_iam_role.api_lambda.arn
  publish = true # creates a new numbered version on every apply — enables rollback

  timeout     = 60 # temporarily raised for diagnostics; reduce to 30 once stable
  memory_size = 256

  # Inside the VPC so it can reach RDS directly over the private subnet.
  # Secrets Manager is reachable via the Interface VPC endpoint.
  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.lambda_sg_id]
  }

  environment {
    variables = {
      ENVIRONMENT      = var.environment
      DB_HOST          = var.db_host
      DB_NAME          = var.db_name
      DB_USERNAME      = var.db_username
      DB_PORT          = "5432"
      DB_SECRET_ARN    = var.db_secret_arn
      REDIS_SECRET_ARN = var.redis_secret_arn
      # Upstash Redis is not reachable from the VPC private subnet (no NAT
      # Gateway). Disabling Redis prevents the OS-level TCP retransmit hang
      # (~75 s) that occurs when SYN packets are silently dropped.
      # To enable: add a NAT Gateway or move the Lambda outside the VPC
      # with an RDS Proxy, then set this to "true".
      REDIS_ENABLED = "false"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.api,
    aws_iam_role_policy_attachment.api_vpc_execution,
    aws_iam_role_policy.api_inline,
  ]

  tags = { Name = "${local.name_prefix}-api" }
}

resource "aws_lambda_alias" "api_prod" {
  name             = "prod"
  description      = "Production alias — points to the live API Lambda version."
  function_name    = aws_lambda_function.api.arn
  function_version = aws_lambda_function.api.version
}

# ---------------------------------------------------------------------------
# API Gateway — HTTP API (v2)
# Cheaper and lower-latency than REST API (v1). Auto-deploy on the $default
# stage means every alias update is live immediately.
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "main" {
  name          = "${local.name_prefix}-api"
  protocol_type = "HTTP"
  description   = "HTTP API for the US gas price dashboard."

  cors_configuration {
    allow_origins = ["*"] # tightened to CloudFront URL in Phase 6
    allow_methods = ["GET", "OPTIONS"]
    allow_headers = ["Content-Type", "Authorization"]
    max_age       = 300
  }

  tags = { Name = "${local.name_prefix}-api-gateway" }
}

# Lambda proxy integration — API Gateway forwards the full request and returns
# the Lambda response verbatim. payload_format_version "2.0" is required for
# HTTP API and is what Mangum auto-detects.
resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.api_prod.invoke_arn
  payload_format_version = "2.0"
}

# Route: any method on any path → Lambda integration
resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# Root route: ANY / for the /docs path and bare health checks
resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# $default stage with auto_deploy — changes go live on every Terraform apply
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  tags = { Name = "${local.name_prefix}-api-gateway-stage" }
}

# Allow API Gateway to invoke the prod alias
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  # execution_arn/*/*  covers all stages, all methods
  source_arn = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
  qualifier  = aws_lambda_alias.api_prod.name
}
