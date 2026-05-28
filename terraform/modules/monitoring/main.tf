locals {
  name_prefix = "${var.project}-${var.environment}"

  # Extract SQS queue name from ARN: arn:aws:sqs:region:account:queue-name
  dlq_name = element(split(":", var.dlq_arn), 5)
}

# ---------------------------------------------------------------------------
# CloudWatch RUM — Real User Monitoring
#
# Captures page views, sessions, Web Vitals (LCP/FID/CLS), JS errors, and
# HTTP request traces from the React frontend running in visitors' browsers.
#
# Architecture:
#   Browser → Cognito Identity Pool (unauthenticated guest role)
#           → RUM PutRumEvents API → CloudWatch RUM App Monitor
#
# The Cognito Identity Pool issues short-lived AWS credentials to anonymous
# browsers. The guest IAM role restricts those credentials to ONLY the
# rum:PutRumEvents action on this specific app monitor — no other AWS
# resources are accessible.
#
# Cost: 1M RUM events/month free for 3 months, then $1 per 100k events.
# At low traffic (~1k sessions/day × ~10 events/session = ~300k events/mo)
# this stays near free.
# ---------------------------------------------------------------------------

# Cognito Identity Pool: issues temporary AWS credentials to browser visitors
# so they can call the RUM PutRumEvents endpoint without an IAM user/key.
resource "aws_cognito_identity_pool" "rum" {
  identity_pool_name               = "${local.name_prefix}-rum-identity-pool"
  allow_unauthenticated_identities = true # browsers are anonymous visitors

  tags = { Name = "${local.name_prefix}-rum-identity-pool" }
}

# IAM role assumed by unauthenticated Cognito identities (i.e. browser visitors).
# Trust policy restricts assumption to the specific Cognito pool above.
resource "aws_iam_role" "rum_unauth" {
  name        = "${local.name_prefix}-rum-unauth-role"
  description = "Assumed by anonymous browser visitors via Cognito to send RUM telemetry."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "CognitoUnauthenticated"
      Effect = "Allow"
      Principal = {
        Federated = "cognito-identity.amazonaws.com"
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        # Scope to this exact identity pool — prevents other pools using this role
        StringEquals = {
          "cognito-identity.amazonaws.com:aud" = aws_cognito_identity_pool.rum.id
        }
        # Require the unauthenticated flow specifically
        "ForAnyValue:StringLike" = {
          "cognito-identity.amazonaws.com:amr" = "unauthenticated"
        }
      }
    }]
  })

  tags = { Name = "${local.name_prefix}-rum-unauth-role" }
}

# Inline policy: the ONLY thing a browser visitor can do with these credentials
# is push RUM events to this specific app monitor. Nothing else.
resource "aws_iam_role_policy" "rum_unauth_inline" {
  name = "${local.name_prefix}-rum-unauth-policy"
  role = aws_iam_role.rum_unauth.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "AllowRumPutEvents"
      Effect   = "Allow"
      Action   = ["rum:PutRumEvents"]
      Resource = aws_rum_app_monitor.frontend.arn
    }]
  })
}

# Attach the unauthenticated role to the Cognito identity pool.
resource "aws_cognito_identity_pool_roles_attachment" "rum" {
  identity_pool_id = aws_cognito_identity_pool.rum.id
  roles = {
    "unauthenticated" = aws_iam_role.rum_unauth.arn
  }
}

# CloudWatch RUM App Monitor — the central resource that receives telemetry.
resource "aws_rum_app_monitor" "frontend" {
  name   = "${local.name_prefix}-frontend"
  domain = var.cloudfront_domain # scopes RUM to this origin only

  app_monitor_configuration {
    # Anonymous visitors get Cognito credentials from this pool
    identity_pool_id = aws_cognito_identity_pool.rum.id
    guest_role_arn   = aws_iam_role.rum_unauth.arn

    # Capture 100% of sessions at current traffic levels.
    # Reduce to 0.1 (10%) if monthly events approach 1M to stay in free tier.
    session_sample_rate = 1.0

    # telemetries:
    #   "errors"      — uncaught JS exceptions and promise rejections
    #   "performance" — Web Vitals (LCP, FID, CLS, TTFB) + navigation timing
    #   "http"        — fetch/XHR calls including URL, status, latency
    telemetries = ["errors", "performance", "http"]

    allow_cookies = true  # enables cross-session user identification
    enable_xray   = false # X-Ray distributed tracing — skip to avoid added cost
  }

  custom_events {
    status = "DISABLED" # enable later if you want to track custom interactions
  }

  tags = { Name = "${local.name_prefix}-rum-app-monitor" }
}

# ---------------------------------------------------------------------------
# SNS topic + email subscription
# All alarms fire to this topic. The subscription sends an email confirmation
# on first apply — you must click the link before alerts are delivered.
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"

  tags = { Name = "${local.name_prefix}-alerts" }
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------------------------------------------------------------------------
# Alarm 1 — Ingest Lambda errors
# Any error (exception / timeout) in the ingest function triggers an alert.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ingest_errors" {
  alarm_name          = "${local.name_prefix}-ingest-errors"
  alarm_description   = "Ingest Lambda threw an error or timed out."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching" # no invocations = no errors

  dimensions = {
    FunctionName = var.ingest_function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${local.name_prefix}-ingest-errors-alarm" }
}

# ---------------------------------------------------------------------------
# Alarm 2 — Transform Lambda errors
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "transform_errors" {
  alarm_name          = "${local.name_prefix}-transform-errors"
  alarm_description   = "Transform Lambda threw an error or timed out."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = var.transform_function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${local.name_prefix}-transform-errors-alarm" }
}

# ---------------------------------------------------------------------------
# Alarm 3 — API Lambda error rate > 5 %
# Uses metric math: (Errors / Invocations) * 100 > 5.
# treat_missing_data = notBreaching so quiet periods don't false-alarm.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "api_error_rate" {
  alarm_name          = "${local.name_prefix}-api-error-rate"
  alarm_description   = "API Lambda error rate exceeded 5 % over the last 5 minutes."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 5
  treat_missing_data  = "notBreaching"

  metric_query {
    id    = "errors"
    label = "API Errors"
    metric {
      metric_name = "Errors"
      namespace   = "AWS/Lambda"
      period      = 300
      stat        = "Sum"
      dimensions  = { FunctionName = var.api_function_name }
    }
  }

  metric_query {
    id    = "invocations"
    label = "API Invocations"
    metric {
      metric_name = "Invocations"
      namespace   = "AWS/Lambda"
      period      = 300
      stat        = "Sum"
      dimensions  = { FunctionName = var.api_function_name }
    }
  }

  metric_query {
    id          = "error_rate"
    label       = "Error Rate (%)"
    expression  = "IF(invocations > 0, errors / invocations * 100, 0)"
    return_data = true
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${local.name_prefix}-api-error-rate-alarm" }
}

# ---------------------------------------------------------------------------
# Alarm 4 — SQS Dead Letter Queue depth > 0
# A message in the DLQ means the ingest Lambda failed all 3 retries.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${local.name_prefix}-dlq-depth"
  alarm_description   = "Messages appeared in the ingest DLQ — all retries exhausted."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = local.dlq_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${local.name_prefix}-dlq-depth-alarm" }
}

# ---------------------------------------------------------------------------
# Alarm 5 — RDS CPU > 80 % for 10 minutes (2 × 5 min periods)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${local.name_prefix}-rds-cpu"
  alarm_description   = "RDS CPU utilisation above 80 % for 10 consecutive minutes."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "missing"

  dimensions = {
    DBInstanceIdentifier = var.rds_instance_id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${local.name_prefix}-rds-cpu-alarm" }
}

# ---------------------------------------------------------------------------
# Alarm 6 — API Lambda p99 duration > 3 000 ms
# Uses extended_statistic so CloudWatch computes the 99th-percentile duration.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "api_p99_latency" {
  alarm_name          = "${local.name_prefix}-api-p99-latency"
  alarm_description   = "API Lambda p99 execution time exceeded 3 000 ms."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistic  = "p99"
  threshold           = 3000
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = var.api_function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${local.name_prefix}-api-p99-latency-alarm" }
}

# ---------------------------------------------------------------------------
# Alarm 7 — API Gateway 5xx errors (health check proxy)
# HTTP API v2 emits 5xx metric in AWS/ApiGateway namespace.
# 2 consecutive 1-minute periods with any 5xx fires the alarm.
# (A proper active health check would use CloudWatch Synthetics — ~$1.70/mo.)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name_prefix}-api-5xx"
  alarm_description   = "API Gateway is returning 5xx errors for 2 consecutive minutes."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "5xx"
  namespace           = "AWS/ApiGateway"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    ApiId = var.api_gateway_id
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${local.name_prefix}-api-5xx-alarm" }
}
