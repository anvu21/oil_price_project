output "sns_topic_arn" {
  description = "ARN of the SNS topic that receives all CloudWatch alarm notifications."
  value       = aws_sns_topic.alerts.arn
}

output "sns_topic_name" {
  description = "Name of the SNS alerts topic."
  value       = aws_sns_topic.alerts.name
}

output "rum_app_monitor_id" {
  description = "CloudWatch RUM app monitor ID — embedded in the frontend JS snippet."
  value       = aws_rum_app_monitor.frontend.app_monitor_id
}

output "rum_identity_pool_id" {
  description = "Cognito Identity Pool ID — used by the RUM JS client to get temporary credentials."
  value       = aws_cognito_identity_pool.rum.id
}
