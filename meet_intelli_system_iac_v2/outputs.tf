# =============================================================================
# V2 Outputs
# =============================================================================

# --- Networking ---

output "private_subnet_ids" {
  description = "V2 private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "ecs_security_group_id" {
  description = "V2 ECS security group ID"
  value       = aws_security_group.ecs_v2.id
}

# --- Storage ---

output "s3_raw_bucket" {
  description = "S3 bucket for raw transcripts"
  value       = aws_s3_bucket.raw.id
}

output "s3_derived_bucket" {
  description = "S3 bucket for derived artifacts"
  value       = aws_s3_bucket.derived.id
}

output "s3_vectors_bucket" {
  description = "S3 Vectors bucket name"
  value       = aws_s3vectors_vector_bucket.vectors.vector_bucket_name
}

output "s3_vectors_index" {
  description = "S3 Vectors index name"
  value       = aws_s3vectors_index.meeting_segments.index_name
}

output "dynamodb_table" {
  description = "DynamoDB meetings metadata table"
  value       = aws_dynamodb_table.meetings.name
}

# --- ECR ---

output "api_ecr_url" {
  description = "V2 API ECR repository URL"
  value       = aws_ecr_repository.api.repository_url
}

output "ui_ecr_url" {
  description = "V2 UI ECR repository URL"
  value       = aws_ecr_repository.ui.repository_url
}

output "worker_ecr_url" {
  description = "V2 Worker ECR repository URL"
  value       = aws_ecr_repository.worker.repository_url
}

# --- ECS ---

output "ecs_cluster_name" {
  description = "V2 ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "worker_task_def_family" {
  description = "Worker task definition family (for RunTask)"
  value       = var.deploy_app ? aws_ecs_task_definition.worker[0].family : ""
}

# --- ALB (read-only from V1) ---

output "alb_dns" {
  description = "ALB DNS name (owned by V1, shared)"
  value       = data.aws_lb.main.dns_name
}

output "v2_api_url" {
  description = "V2 API base URL"
  value       = "http://${data.aws_lb.main.dns_name}/api/v2"
}

output "v2_ui_url" {
  description = "V2 UI URL (during transition)"
  value       = "http://${data.aws_lb.main.dns_name}/v2/"
}

# --- GitHub Actions ---

output "github_actions_role_arn" {
  description = "V2 GitHub Actions IAM role ARN"
  value       = aws_iam_role.github_actions_role.arn
}
