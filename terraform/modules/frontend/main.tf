locals {
  name_prefix = "${var.project}-${var.environment}"
}

# ---------------------------------------------------------------------------
# S3 bucket — private, CloudFront is the only allowed origin
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "frontend" {
  bucket        = "${local.name_prefix}-frontend-${random_id.suffix.hex}"
  force_destroy = true

  tags = { Name = "${local.name_prefix}-frontend" }
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# CloudFront Origin Access Control — lets CloudFront read the private bucket
# ---------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${local.name_prefix}-frontend-oac"
  description                       = "OAC for the ${local.name_prefix} frontend bucket."
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ---------------------------------------------------------------------------
# S3 bucket policy — allow CloudFront OAC to read objects
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "frontend_bucket" {
  statement {
    sid     = "AllowCloudFrontOAC"
    actions = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.frontend]
}

# ---------------------------------------------------------------------------
# CloudFront distribution
# ---------------------------------------------------------------------------

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = "${local.name_prefix} gas price dashboard"
  price_class         = "PriceClass_100" # US + Europe only — cheapest tier

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-frontend"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    # 1 hour for hashed assets, 0 for index.html (SPA routing)
    min_ttl     = 0
    default_ttl = 3600
    max_ttl     = 86400
  }

  # SPA fallback — return index.html for any 404 so React Router works
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true # free *.cloudfront.net certificate
  }

  tags = { Name = "${local.name_prefix}-frontend-cdn" }
}
