# =============================================================================
# DynamoDB — MeetingsMetadata table
# =============================================================================

resource "aws_dynamodb_table" "meetings" {
  name         = "${var.project_name}-MeetingsMetadata"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "meeting_id"

  attribute {
    name = "meeting_id"
    type = "S"
  }

  tags = {
    Name    = "${var.project_name}-MeetingsMetadata"
    Project = var.project_name
  }
}
