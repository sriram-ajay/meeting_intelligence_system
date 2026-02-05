variable "aws_region" {
  description = "AWS Region to deploy resources"
  type        = string
  default     = "eu-west-2"
}

variable "project_name" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "meeting-intel"
}

variable "bedrock_llm_id" {
  description = "Bedrock Model ID for LLM"
  type        = string
  default     = "anthropic.claude-3-haiku-20240307-v1:0"
}

variable "bedrock_embed_id" {
  description = "Bedrock Model ID for Embeddings (deprecated, kept for backward compatibility)"
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "embed_provider" {
  description = "Embedding provider: 'openai' or 'bedrock'"
  type        = string
  default     = "openai"
}

variable "llm_provider" {
  description = "LLM provider: 'openai' or 'bedrock'"
  type        = string
  default     = "bedrock"
}

variable "openai_secret_name" {
  description = "Name of the AWS Secrets Manager secret containing the OpenAI API Key"
  type        = string
  default     = "openai_api_key"
}

variable "app_name" {
  description = "Application display name"
  type        = string
  default     = "Meeting Intelligence System"
}

variable "app_version" {
  description = "Application semantic version for API documentation"
  type        = string
  default     = "1.0.0"
}

variable "app_description" {
  description = "Application description for API documentation"
  type        = string
  default     = "RAG-powered meeting intelligence system"
}

variable "api_version" {
  description = "API version string (v1, v2, etc.) - used in endpoint path /api/{version}"
  type        = string
  default     = "v1"
}

variable "api_host" {
  description = "API service hostname (localhost for same container, service name for separate services, or ALB DNS)"
  type        = string
  default     = "localhost"
}

variable "api_port" {
  description = "API service port"
  type        = number
  default     = 8000
}

variable "api_protocol" {
  description = "Protocol for API communication (http or https)"
  type        = string
  default     = "http"
}

variable "deploy_app" {
  description = "Toggle to deploy ECS services and ALB. Set to false for foundation only."
  type        = bool
  default     = false
}

variable "private_subnets" {
  description = "List of private subnet IDs for ECS tasks (from network.tf)"
  type        = list(string)
  default     = [] # Will be updated by outputs from network module
}
