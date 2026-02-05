resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "data_store" {
  bucket        = "${var.project_name}-data-store-${random_id.bucket_suffix.hex}"
  force_destroy = true
  
  tags = {
    Project = var.project_name
  }
}

resource "aws_s3_bucket_public_access_block" "data_store_block" {
  bucket = aws_s3_bucket.data_store.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
