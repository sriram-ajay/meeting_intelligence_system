output "s3_bucket_name" {
  value = aws_s3_bucket.data_store.id
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ui_url" {
  description = "Access the Streamlit UI here (Once deployed)"
  value       = "http://${aws_lb.main.dns_name}"
}

output "api_ecr_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ui_ecr_url" {
  value = aws_ecr_repository.ui.repository_url
}

output "api_configuration" {
  description = "API configuration passed to UI service"
  value = {
    host = var.api_host
    port = var.api_port
    url  = "http://${var.api_host}:${var.api_port}/api/v1"
  }
}
