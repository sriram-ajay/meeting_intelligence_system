# --- ECS Infrastructure ---

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project_name}-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 7
  tags = { Name = "${var.project_name}-logs" }
}

# --- ECS Task Definition (Combined API + UI) ---

resource "aws_ecs_task_definition" "app" {
  count                    = var.deploy_app ? 1 : 0
  family                   = "${var.project_name}-app"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 2048
  memory                   = 4096
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.api.repository_url}:latest"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
        }
      ]
      environment = [
        { name = "APP_NAME", value = var.app_name },
        { name = "APP_VERSION", value = var.app_version },
        { name = "APP_DESCRIPTION", value = var.app_description },
        { name = "API_VERSION", value = var.api_version },
        { name = "API_HOST", value = var.api_host },
        { name = "API_PORT", value = tostring(var.api_port) },
        { name = "API_PROTOCOL", value = var.api_protocol },
        { name = "DATABASE_URI", value = "s3://${aws_s3_bucket.data_store.id}/lancedb" },
        { name = "ENVIRONMENT", value = "production" },
        { name = "BEDROCK_REGION", value = var.aws_region },
        { name = "BEDROCK_LLM_MODEL_ID", value = var.bedrock_llm_id },
        { name = "LLM_PROVIDER", value = var.llm_provider },
        { name = "EMBED_PROVIDER", value = var.embed_provider },
        { name = "OPENAI_SECRET_NAME", value = var.openai_secret_name }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    },
    {
      name      = "ui"
      image     = "${aws_ecr_repository.ui.repository_url}:latest"
      essential = true
      portMappings = [
        {
          containerPort = 8501
          hostPort      = 8501
        }
      ]
      environment = [
        { name = "APP_NAME", value = var.app_name },
        { name = "APP_VERSION", value = var.app_version },
        { name = "APP_DESCRIPTION", value = var.app_description },
        { name = "API_VERSION", value = var.api_version },
        { name = "API_HOST", value = "localhost" }, # UI talks to API on localhost within same task
        { name = "API_PORT", value = "8000" },
        { name = "API_PROTOCOL", value = "http" },
        { name = "DATABASE_URI", value = "s3://${aws_s3_bucket.data_store.id}/lancedb" },
        { name = "ENVIRONMENT", value = "production" },
        { name = "BEDROCK_REGION", value = var.aws_region },
        { name = "BEDROCK_LLM_MODEL_ID", value = var.bedrock_llm_id },
        { name = "LLM_PROVIDER", value = var.llm_provider },
        { name = "EMBED_PROVIDER", value = var.embed_provider },
        { name = "OPENAI_SECRET_NAME", value = var.openai_secret_name }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ui"
        }
      }
    }
  ])
}

# --- ECS Service ---

resource "aws_ecs_service" "app" {
  count           = var.deploy_app ? 1 : 0
  name            = "${var.project_name}-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"
  health_check_grace_period_seconds = 180

  load_balancer {
    target_group_arn = aws_lb_target_group.ui[0].arn
    container_name   = "ui"
    container_port   = 8501
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api[0].arn
    container_name   = "api"
    container_port   = 8000
  }

  network_configuration {
    security_groups = [aws_security_group.ecs_sg.id]
    subnets         = aws_subnet.public[*].id
    assign_public_ip = true
  }
}
