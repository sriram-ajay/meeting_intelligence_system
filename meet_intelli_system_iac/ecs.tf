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

# --- API Task Definition ---
resource "aws_ecs_task_definition" "api" {
  count                    = var.deploy_app ? 1 : 0
  family                   = "${var.project_name}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
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
    }
  ])
}

# --- UI Task Definition ---
resource "aws_ecs_task_definition" "ui" {
  count                    = var.deploy_app ? 1 : 0
  family                   = "${var.project_name}-ui"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
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
        { name = "ENVIRONMENT", value = "production" },
        { name = "API_HOST", value = aws_lb.main.dns_name }, # Now pointing to ALB DNS
        { name = "API_PORT", value = "80" },               # Talking to ALB on port 80
        { name = "API_PROTOCOL", value = "http" }
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

# --- API ECS Service ---
resource "aws_ecs_service" "api" {
  count           = var.deploy_app ? 1 : 0
  name            = "${var.project_name}-api-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"
  health_check_grace_period_seconds = 180

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

  depends_on = [aws_lb_listener_rule.api]
}

# --- UI ECS Service ---
resource "aws_ecs_service" "ui" {
  count           = var.deploy_app ? 1 : 0
  name            = "${var.project_name}-ui-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ui[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"
  health_check_grace_period_seconds = 180

  load_balancer {
    target_group_arn = aws_lb_target_group.ui[0].arn
    container_name   = "ui"
    container_port   = 8501
  }

  network_configuration {
    security_groups = [aws_security_group.ecs_sg.id]
    subnets         = aws_subnet.public[*].id
    assign_public_ip = true
  }

  depends_on = [aws_lb_listener.http]
}
