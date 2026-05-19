output "bucket_name" {
  description = "S3 bucket name for the frontend build artefacts."
  value       = aws_s3_bucket.frontend.bucket
}

output "bucket_arn" {
  description = "S3 bucket ARN."
  value       = aws_s3_bucket.frontend.arn
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain (e.g. dXXXXXXXX.cloudfront.net)."
  value       = aws_cloudfront_distribution.frontend.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID — needed to invalidate the cache after deploy."
  value       = aws_cloudfront_distribution.frontend.id
}
