output "sns_topic_arn" {
  description = "ARN of the SNS topic that receives all CloudWatch alarm notifications."
  value       = aws_sns_topic.alerts.arn
}

output "sns_topic_name" {
  description = "Name of the SNS alerts topic."
  value       = aws_sns_topic.alerts.name
}
