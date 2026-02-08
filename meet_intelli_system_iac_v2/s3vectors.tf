# =============================================================================
# S3 Vectors — separate resource type from regular S3
#
# Uses aws_s3vectors_vector_bucket (NOT aws_s3_bucket).
# Requires AWS provider ~> 6.0.
# =============================================================================

resource "aws_s3vectors_vector_bucket" "vectors" {
  vector_bucket_name = "${var.project_name}-vectors"
  force_destroy      = true

  tags = {
    Name    = "${var.project_name}-vectors"
    Project = var.project_name
  }
}

resource "aws_s3vectors_index" "meeting_segments" {
  vector_bucket_name = aws_s3vectors_vector_bucket.vectors.vector_bucket_name
  index_name         = "${var.project_name}-meeting-segments"

  data_type       = "float32"
  dimension       = var.vector_dimension
  distance_metric = var.vector_distance_metric

  metadata_configuration {
    non_filterable_metadata_keys = ["text", "speaker"]
  }

  tags = {
    Name    = "${var.project_name}-meeting-segments-index"
    Project = var.project_name
  }
}
