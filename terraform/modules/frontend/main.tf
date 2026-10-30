locals {
  name_prefix     = "${var.project}-${var.environment}"
  worthit_enabled = var.worthit_bucket_regional_domain != ""
}

# ---------------------------------------------------------------------------
# WorthItFood — rewrite directory-style URLs to index.html. The distribution's
# 403/404 → /index.html fallback would otherwise serve the gas price app.
# ---------------------------------------------------------------------------

resource "aws_cloudfront_function" "worthit_index" {
  count   = local.worthit_enabled ? 1 : 0
  name    = "${local.name_prefix}-worthit-index"
  runtime = "cloudfront-js-2.0"
  comment = "Serve /worthit/index.html for /worthit and /worthit/"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      var uri = request.uri;
      if (uri === '/worthit') {
        return { statusCode: 301, statusDescription: 'Moved Permanently', headers: { location: { value: '/worthit/' } } };
      }
      if (uri.endsWith('/') || uri.split('/').pop().indexOf('.') === -1) {
        request.uri = '/worthit/index.html';
      }
      return request;
    }
  EOT
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
    sid       = "AllowCloudFrontOAC"
    actions   = ["s3:GetObject"]
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

  # WorthItFood: its own bucket (so oil's `s3 sync --delete` can never touch it),
  # reusing this distribution's OAC. Absent unless the bucket domain is provided.
  dynamic "origin" {
    for_each = local.worthit_enabled ? [1] : []
    content {
      domain_name              = var.worthit_bucket_regional_domain
      origin_id                = "s3-worthit"
      origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = local.worthit_enabled ? [1] : []
    content {
      path_pattern           = "/worthit*"
      target_origin_id       = "s3-worthit"
      viewer_protocol_policy = "redirect-to-https"
      allowed_methods        = ["GET", "HEAD"]
      cached_methods         = ["GET", "HEAD"]
      compress               = true

      # Managed "CachingOptimized" — honours the Cache-Control headers set at upload.
      cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

      function_association {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.worthit_index[0].arn
      }
    }
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
