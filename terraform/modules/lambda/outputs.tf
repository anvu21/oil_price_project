output "ingest_function_name" {
  description = "Name of the ingest Lambda function."
  value       = aws_lambda_function.ingest.function_name
}

output "ingest_function_arn" {
  description = "ARN of the ingest Lambda function (unqualified)."
  value       = aws_lambda_function.ingest.arn
}

output "ingest_alias_arn" {
  description = "ARN of the ingest Lambda prod alias. Use this as the invoke target."
  value       = aws_lambda_alias.ingest_prod.arn
}

output "ingest_function_version" {
  description = "The version number published by the most recent terraform apply."
  value       = aws_lambda_function.ingest.version
}

output "dlq_url" {
  description = "SQS DLQ URL. Used by the monitoring module to set a depth alarm."
  value       = aws_sqs_queue.ingest_dlq.url
}

output "dlq_arn" {
  description = "SQS DLQ ARN."
  value       = aws_sqs_queue.ingest_dlq.arn
}

output "eia_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the EIA API key."
  value       = aws_secretsmanager_secret.eia_api_key.arn
  sensitive   = true
}

output "transform_function_name" {
  description = "Name of the transform Lambda function."
  value       = aws_lambda_function.transform.function_name
}

output "transform_function_arn" {
  description = "ARN of the transform Lambda function (unqualified)."
  value       = aws_lambda_function.transform.arn
}

output "transform_alias_arn" {
  description = "ARN of the transform Lambda prod alias."
  value       = aws_lambda_alias.transform_prod.arn
}

output "transform_function_version" {
  description = "The version number published by the most recent terraform apply."
  value       = aws_lambda_function.transform.version
}

output "api_function_name" {
  description = "Name of the API Lambda function."
  value       = aws_lambda_function.api.function_name
}

output "api_function_arn" {
  description = "ARN of the API Lambda function (unqualified)."
  value       = aws_lambda_function.api.arn
}

output "api_alias_arn" {
  description = "ARN of the API Lambda prod alias. Used by API Gateway integration."
  value       = aws_lambda_alias.api_prod.arn
}

output "api_invoke_url" {
  description = "Base URL of the API Gateway HTTP API (e.g. https://xxx.execute-api.us-east-1.amazonaws.com)."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "api_gateway_id" {
  description = "API Gateway HTTP API ID — used as a CloudWatch dimension."
  value       = aws_apigatewayv2_api.main.id
}
