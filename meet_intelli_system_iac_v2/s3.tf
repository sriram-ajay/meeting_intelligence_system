# =============================================================================
# V2 S3 Buckets — regular S3 for raw transcripts and derived artifacts
# =============================================================================

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

# --- Raw Transcript Bucket ---

resource "aws_s3_bucket" "raw" {
  bucket        = "${var.project_name}-raw-${random_id.bucket_suffix.hex}"
  force_destroy = true

  tags = {
    Name    = "${var.project_name}-raw"
    Project = var.project_name
  }
}

resource "aws_s3_bucket_public_access_block" "raw_block" {
  bucket = aws_s3_bucket.raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "raw_versioning" {
  bucket = aws_s3_bucket.raw.id

  versioning_configuration {
    status = "Enabled"
  }
}

# --- Derived Artifacts Bucket (chunk_map, normalized transcripts, eval results) ---

resource "aws_s3_bucket" "derived" {
  bucket        = "${var.project_name}-derived-${random_id.bucket_suffix.hex}"
  force_destroy = true

  tags = {
    Name    = "${var.project_name}-derived"
    Project = var.project_name
  }
}

resource "aws_s3_bucket_public_access_block" "derived_block" {
  bucket = aws_s3_bucket.derived.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "derived_versioning" {
  bucket = aws_s3_bucket.derived.id

  versioning_configuration {
    status = "Enabled"
  }
}
