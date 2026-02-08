# =============================================================================
# Read-only data sources — looks up V1 resources, NEVER modifies them.
# If V1 resources are renamed/destroyed, these will fail at plan time
# (safe — no destructive action).
# =============================================================================

data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {}

# --- VPC (owned by V1) ---

data "aws_vpc" "main" {
  tags = {
    Name = "${var.v1_project_name}-vpc"
  }
}

# --- Public Subnets (owned by V1, used for ALB only) ---

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }

  tags = {
    Name = "${var.v1_project_name}-public-subnet-*"
  }
}

# --- ALB (owned by V1, V2 only adds listener rules) ---

data "aws_lb" "main" {
  name = "${var.v1_project_name}-alb"
}

data "aws_lb_listener" "http" {
  load_balancer_arn = data.aws_lb.main.arn
  port              = 80
}

# --- V1 Security Groups (read-only — V2 creates its own SG) ---

data "aws_security_group" "lb_sg" {
  name   = "${var.v1_project_name}-lb-sg"
  vpc_id = data.aws_vpc.main.id
}

# --- Internet Gateway (needed to attach S3 gateway to public route table) ---

data "aws_internet_gateway" "main" {
  filter {
    name   = "attachment.vpc-id"
    values = [data.aws_vpc.main.id]
  }
}

# --- Public route table (needed to add S3/DynamoDB gateway endpoints) ---

data "aws_route_table" "public" {
  vpc_id = data.aws_vpc.main.id

  filter {
    name   = "route.gateway-id"
    values = [data.aws_internet_gateway.main.id]
  }
}

# --- GitHub OIDC Provider (owned by V1, V2 references it for its own role) ---

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}
