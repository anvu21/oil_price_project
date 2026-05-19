output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "IDs of the two public subnets."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of the two private subnets (for Lambda, RDS, ElastiCache)."
  value       = aws_subnet.private[*].id
}

output "lambda_sg_id" {
  description = "Security group ID for Lambda functions."
  value       = aws_security_group.lambda.id
}

output "rds_sg_id" {
  description = "Security group ID for RDS."
  value       = aws_security_group.rds.id
}

