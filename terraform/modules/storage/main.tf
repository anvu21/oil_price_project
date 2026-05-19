locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# ---------------------------------------------------------------------------
# Raw bucket — EIA API JSON responses, written by ingest Lambda
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "raw" {
  bucket = "${local.name_prefix}-raw-${random_id.bucket_suffix.hex}"

  tags = { Name = "${local.name_prefix}-raw" }
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket = aws_s3_bucket.raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    id     = "tiered-storage"
    status = "Enabled"

    filter {}

    transition {
      days          = var.raw_retention_days_ia
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = var.raw_retention_days_glacier
      storage_class = "GLACIER"
    }
  }
}

# ---------------------------------------------------------------------------
# Processed bucket — aggregated data written by transform Lambda
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "processed" {
  bucket = "${local.name_prefix}-processed-${random_id.bucket_suffix.hex}"

  tags = { Name = "${local.name_prefix}-processed" }
}

resource "aws_s3_bucket_versioning" "processed" {
  bucket = aws_s3_bucket.processed.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "processed" {
  bucket = aws_s3_bucket.processed.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "processed" {
  bucket = aws_s3_bucket.processed.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
