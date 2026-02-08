# =============================================================================
# V2 ECS — own cluster, log group, task definitions, services
# Completely separate from V1.
# =============================================================================

# --- ECS Cluster (V2 owns) ---

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name    = "${var.project_name}-cluster"
    Project = var.project_name
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

# --- CloudWatch Log Group ---

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 14

  tags = {
    Name    = "${var.project_name}-logs"
    Project = var.project_name
  }
}

# =============================================================================
# API Task Definition
# =============================================================================

resource "aws_ecs_task_definition" "api" {
  count                    = var.deploy_app ? 1 : 0
  family                   = "${var.project_name}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:latest"
    essential = true

    portMappings = [{
      containerPort = 8000
      hostPort      = 8000
      protocol      = "tcp"
    }]

    environment = [
      { name = "APP_NAME", value = var.app_name },
      { name = "APP_VERSION", value = var.app_version },
      { name = "APP_DESCRIPTION", value = var.app_description },
      { name = "ENVIRONMENT", value = var.environment },
      { name = "AWS_REGION", value = var.aws_region },

      # LLM / Embedding
      { name = "LLM_PROVIDER", value = var.llm_provider },
      { name = "EMBED_PROVIDER", value = var.embed_provider },
      { name = "BEDROCK_REGION", value = var.aws_region },
      { name = "BEDROCK_LLM_MODEL_ID", value = var.bedrock_llm_id },
      { name = "BEDROCK_EMBED_MODEL_ID", value = var.bedrock_embed_id },
      { name = "OPENAI_SECRET_NAME", value = var.openai_secret_name },

      # S3 (regular buckets)
      { name = "S3_RAW_BUCKET", value = aws_s3_bucket.raw.id },
      { name = "S3_RAW_PREFIX", value = "raw" },
      { name = "S3_DERIVED_BUCKET", value = aws_s3_bucket.derived.id },
      { name = "S3_DERIVED_PREFIX", value = "derived" },

      # DynamoDB
      { name = "DYNAMODB_TABLE_NAME", value = aws_dynamodb_table.meetings.name },

      # S3 Vectors
      { name = "S3_VECTORS_BUCKET", value = aws_s3vectors_vector_bucket.vectors.vector_bucket_name },
      { name = "S3_VECTORS_INDEX_NAME", value = aws_s3vectors_index.meeting_segments.index_name },

      # ECS Worker (API triggers RunTask)
      { name = "ECS_CLUSTER_NAME", value = aws_ecs_cluster.main.name },
      { name = "ECS_WORKER_TASK_DEF", value = "${var.project_name}-worker" },
      { name = "ECS_WORKER_SUBNETS", value = join(",", aws_subnet.private[*].id) },
      { name = "ECS_WORKER_SECURITY_GROUP", value = aws_security_group.ecs_v2.id },
      { name = "ECS_WORKER_CONTAINER_NAME", value = "worker" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])

  tags = {
    Name    = "${var.project_name}-api-task"
    Project = var.project_name
  }
}

# =============================================================================
# UI Task Definition
# =============================================================================

resource "aws_ecs_task_definition" "ui" {
  count                    = var.deploy_app ? 1 : 0
  family                   = "${var.project_name}-ui"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ui_cpu
  memory                   = var.ui_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name      = "ui"
    image     = "${aws_ecr_repository.ui.repository_url}:latest"
    essential = true

    portMappings = [{
      containerPort = 8501
      hostPort      = 8501
      protocol      = "tcp"
    }]

    environment = [
      { name = "APP_NAME", value = var.app_name },
      { name = "APP_VERSION", value = var.app_version },
      { name = "ENVIRONMENT", value = var.environment },
      { name = "AWS_REGION", value = var.aws_region },

      # UI talks to API directly via Cloud Map (private DNS)
      # Resolves to api.meeting-intel-v2.local -> API container private IP
      { name = "API_HOST", value = "api.${var.project_name}.local" },
      { name = "API_PORT", value = "8000" },
      { name = "API_PROTOCOL", value = "http" },

      # LLM / Embedding (required by shared Settings model)
      { name = "LLM_PROVIDER", value = var.llm_provider },
      { name = "EMBED_PROVIDER", value = var.embed_provider },
      { name = "BEDROCK_REGION", value = var.aws_region },
      { name = "BEDROCK_LLM_MODEL_ID", value = var.bedrock_llm_id },
      { name = "BEDROCK_EMBED_MODEL_ID", value = var.bedrock_embed_id },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ui"
      }
    }
  }])

  tags = {
    Name    = "${var.project_name}-ui-task"
    Project = var.project_name
  }
}

# =============================================================================
# Worker Task Definition (triggered by API via ECS RunTask)
# MEETING_ID and S3_KEY are passed as container overrides at runtime.
# =============================================================================

resource "aws_ecs_task_definition" "worker" {
  count                    = var.deploy_app ? 1 : 0
  family                   = "${var.project_name}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name      = "worker"
    image     = "${aws_ecr_repository.worker.repository_url}:latest"
    essential = true

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "AWS_REGION", value = var.aws_region },

      # LLM / Embedding
      { name = "LLM_PROVIDER", value = var.llm_provider },
      { name = "EMBED_PROVIDER", value = var.embed_provider },
      { name = "BEDROCK_REGION", value = var.aws_region },
      { name = "BEDROCK_LLM_MODEL_ID", value = var.bedrock_llm_id },
      { name = "BEDROCK_EMBED_MODEL_ID", value = var.bedrock_embed_id },
      { name = "OPENAI_SECRET_NAME", value = var.openai_secret_name },

      # S3 (regular buckets)
      { name = "S3_RAW_BUCKET", value = aws_s3_bucket.raw.id },
      { name = "S3_RAW_PREFIX", value = "raw" },
      { name = "S3_DERIVED_BUCKET", value = aws_s3_bucket.derived.id },
      { name = "S3_DERIVED_PREFIX", value = "derived" },

      # DynamoDB
      { name = "DYNAMODB_TABLE_NAME", value = aws_dynamodb_table.meetings.name },

      # S3 Vectors
      { name = "S3_VECTORS_BUCKET", value = aws_s3vectors_vector_bucket.vectors.vector_bucket_name },
      { name = "S3_VECTORS_INDEX_NAME", value = aws_s3vectors_index.meeting_segments.index_name },

      # MEETING_ID and S3_KEY are passed via RunTask container overrides
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])

  tags = {
    Name    = "${var.project_name}-worker-task"
    Project = var.project_name
  }
}

# =============================================================================
# Cloud Map — private DNS namespace for service-to-service discovery
# The UI container resolves api.meeting-intel-v2.local:8000 instead of
# going through the internet-facing ALB (unreachable from private subnets).
# =============================================================================

resource "aws_service_discovery_private_dns_namespace" "main" {
  count = var.deploy_app ? 1 : 0
  name  = "${var.project_name}.local"
  vpc   = data.aws_vpc.main.id

  tags = {
    Name    = "${var.project_name}-namespace"
    Project = var.project_name
  }
}

resource "aws_service_discovery_service" "api" {
  count = var.deploy_app ? 1 : 0
  name  = "api"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main[0].id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
  }

  tags = {
    Name    = "${var.project_name}-api-discovery"
    Project = var.project_name
  }
}

# =============================================================================
# ECS Services (API + UI — worker is RunTask, no service)
# =============================================================================

resource "aws_ecs_service" "api" {
  count           = var.deploy_app ? 1 : 0
  name            = "${var.project_name}-api-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 180

  load_balancer {
    target_group_arn = aws_lb_target_group.v2_api[0].arn
    container_name   = "api"
    container_port   = 8000
  }

  network_configuration {
    security_groups  = [aws_security_group.ecs_v2.id]
    subnets          = aws_subnet.private[*].id
    assign_public_ip = false # Private subnets — no public IPs
  }

  service_registries {
    registry_arn = aws_service_discovery_service.api[0].arn
  }

  depends_on = [aws_lb_listener_rule.v2_api]

  tags = {
    Name    = "${var.project_name}-api-service"
    Project = var.project_name
  }
}

resource "aws_ecs_service" "ui" {
  count           = var.deploy_app ? 1 : 0
  name            = "${var.project_name}-ui-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ui[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 180

  load_balancer {
    target_group_arn = aws_lb_target_group.v2_ui[0].arn
    container_name   = "ui"
    container_port   = 8501
  }

  network_configuration {
    security_groups  = [aws_security_group.ecs_v2.id]
    subnets          = aws_subnet.private[*].id
    assign_public_ip = false
  }

  depends_on = [aws_lb_listener_rule.v2_ui]

  tags = {
    Name    = "${var.project_name}-ui-service"
    Project = var.project_name
  }
}
