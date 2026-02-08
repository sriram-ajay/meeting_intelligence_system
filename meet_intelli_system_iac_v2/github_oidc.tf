# =============================================================================
# V2 GitHub OIDC — references V1's OIDC provider, creates its own role
# =============================================================================

# V1 already created the OIDC provider. V2 reads it via data source
# (see data_sources.tf: data.aws_iam_openid_connect_provider.github)

resource "aws_iam_role" "github_actions_role" {
  name = "${var.project_name}-github-actions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = data.aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*"
        }
      }
    }]
  })

  tags = {
    Name    = "${var.project_name}-github-actions-role"
    Project = var.project_name
  }
}

resource "aws_iam_role_policy" "github_actions_policy" {
  name = "${var.project_name}-github-actions-policy"
  role = aws_iam_role.github_actions_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # ECR: get authorization token (global)
      {
        Sid    = "ECRAuth"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability"
        ]
        Resource = "*"
      },
      # ECR: push images to V2 repos only
      {
        Sid    = "ECRPush"
        Effect = "Allow"
        Action = [
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = [
          aws_ecr_repository.api.arn,
          aws_ecr_repository.ui.arn,
          aws_ecr_repository.worker.arn
        ]
      },
      # ECS: deploy V2 services
      {
        Sid    = "ECS"
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices",
          "ecs:DescribeTaskDefinition",
          "ecs:DescribeTasks",
          "ecs:DescribeClusters",
          "ecs:ListTasks",
          "ecs:RegisterTaskDefinition"
        ]
        Resource = "*"
      },
      # IAM: pass V2 roles to ECS
      {
        Sid    = "PassRole"
        Effect = "Allow"
        Action = "iam:PassRole"
        Resource = [
          aws_iam_role.ecs_task_execution_role.arn,
          aws_iam_role.ecs_task_role.arn
        ]
      }
    ]
  })
}
