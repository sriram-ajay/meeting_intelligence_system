resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  # Enable container insights for monitoring
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

  tags = {
    Name = "${var.project_name}-logs"
  }
}

# API Service Task Definition
resource "aws_ecs_task_definition" "api" {
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
      image     = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/meeting-intelligence-api:latest"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
      environment = [
        {
          name  = "ENVIRONMENT"
          value = "production"
        },
        {
          name  = "DATABASE_URI"
          value = "/data/lancedb"
        }
      ]
    }
  ])

  tags = {
    Name = "${var.project_name}-api-task"
  }
}

# UI Service Task Definition
resource "aws_ecs_task_definition" "ui" {
  family                   = "${var.project_name}-ui"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "ui"
      image     = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/meeting-intelligence-ui:latest"
      essential = true
      portMappings = [
        {
          containerPort = 8501
          hostPort      = 8501
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ui"
        }
      }
      environment = [
        {
          name  = "API_HOST"
          value = "meeting-intel-api-alb"
        },
        {
          name  = "API_PORT"
          value = "8000"
        }
      ]
    }
  ])

  tags = {
    Name = "${var.project_name}-ui-task"
  }
}

# API Service with Blue-Green Deployment
resource "aws_ecs_service" "api" {
  count           = var.deploy_app ? 1 : 0
  name            = "${var.project_name}-api-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnets
    security_groups  = [aws_security_group.ecs_api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  # Blue-Green Deployment Configuration
  deployment_controller {
    type = "ECS"
  }

  deployment_configuration {
    maximum_percent         = 200  # Allow 200% capacity during deployment
    minimum_healthy_percent = 100  # Maintain 100% healthy tasks
    deployment_circuit_breaker {
      enable   = true
      rollback = true  # Automatic rollback on deployment failure
    }
  }

  scheduling_strategy = "REPLICA"

  depends_on = [
    aws_lb_listener.api,
    aws_iam_role_policy.s3_access
  ]

  tags = {
    Name = "${var.project_name}-api-service"
  }
}

# UI Service with Blue-Green Deployment
resource "aws_ecs_service" "ui" {
  count           = var.deploy_app ? 1 : 0
  name            = "${var.project_name}-ui-service"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ui.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnets
    security_groups  = [aws_security_group.ecs_ui.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ui.arn
    container_name   = "ui"
    container_port   = 8501
  }

  # Blue-Green Deployment Configuration
  deployment_controller {
    type = "ECS"
  }

  deployment_configuration {
    maximum_percent         = 200
    minimum_healthy_percent = 100
    deployment_circuit_breaker {
      enable   = true
      rollback = true
    }
  }

  scheduling_strategy = "REPLICA"

  depends_on = [
    aws_lb_listener.ui,
    aws_iam_role_policy.s3_access
  ]

  tags = {
    Name = "${var.project_name}-ui-service"
  }
}
