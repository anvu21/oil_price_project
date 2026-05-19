output "raw_bucket_name" {
  description = "Name of the S3 bucket for raw EIA API responses."
  value       = aws_s3_bucket.raw.id
}

output "raw_bucket_arn" {
  description = "ARN of the raw S3 bucket (for Lambda IAM policies in Phase 2)."
  value       = aws_s3_bucket.raw.arn
}

output "processed_bucket_name" {
  description = "Name of the S3 bucket for transformed data."
  value       = aws_s3_bucket.processed.id
}

output "processed_bucket_arn" {
  description = "ARN of the processed S3 bucket (for Lambda IAM policies in Phase 2)."
  value       = aws_s3_bucket.processed.arn
}
