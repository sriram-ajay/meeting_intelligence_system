# =============================================================================
# V2 Variables
# =============================================================================

# --- General ---

variable "aws_region" {
  description = "AWS Region to deploy resources"
  type        = string
  default     = "eu-west-2"
}

variable "project_name" {
  description = "V2 project name prefix for all resources"
  type        = string
  default     = "meeting-intel-v2"
}

variable "v1_project_name" {
  description = "V1 project name — used to look up existing V1 resources via data sources"
  type        = string
  default     = "meeting-intel"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "production"
}

# --- App Metadata ---

variable "app_name" {
  description = "Application display name"
  type        = string
  default     = "Meeting Intelligence System"
}

variable "app_version" {
  description = "Application semantic version"
  type        = string
  default     = "2.0.0"
}

variable "app_description" {
  description = "Application description for API docs"
  type        = string
  default     = "V2 RAG-powered meeting intelligence system"
}

# --- LLM / Embedding Providers ---

variable "llm_provider" {
  description = "LLM provider: 'bedrock' or 'openai'"
  type        = string
  default     = "bedrock"
}

variable "embed_provider" {
  description = "Embedding provider: 'bedrock' or 'openai'"
  type        = string
  default     = "openai"
}

variable "bedrock_llm_id" {
  description = "Bedrock Model ID for LLM"
  type        = string
  default     = "anthropic.claude-3-haiku-20240307-v1:0"
}

variable "bedrock_embed_id" {
  description = "Bedrock Model ID for Embeddings"
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "openai_secret_name" {
  description = "AWS Secrets Manager secret name for OpenAI API key"
  type        = string
  default     = "openai_api_key"
}

# --- S3 Vectors ---

variable "vector_dimension" {
  description = "Embedding vector dimension (1536 for OpenAI, 1024 for Titan)"
  type        = number
  default     = 1536
}

variable "vector_distance_metric" {
  description = "Distance metric for vector similarity search"
  type        = string
  default     = "cosine"
}

# --- ECS Compute ---

variable "api_cpu" {
  description = "API task CPU units"
  type        = string
  default     = "512"
}

variable "api_memory" {
  description = "API task memory (MiB)"
  type        = string
  default     = "1024"
}

variable "ui_cpu" {
  description = "UI task CPU units"
  type        = string
  default     = "512"
}

variable "ui_memory" {
  description = "UI task memory (MiB)"
  type        = string
  default     = "1024"
}

variable "worker_cpu" {
  description = "Worker task CPU units"
  type        = string
  default     = "1024"
}

variable "worker_memory" {
  description = "Worker task memory (MiB)"
  type        = string
  default     = "2048"
}

# --- Feature Toggles ---

variable "deploy_app" {
  description = "Toggle to deploy ECS services. Set to false for foundation-only deploy."
  type        = bool
  default     = false
}

# --- GitHub ---

variable "github_repo" {
  description = "GitHub repository for OIDC (owner/repo)"
  type        = string
  default     = "sriram-ajay/meeting_intelligence_system"
}
