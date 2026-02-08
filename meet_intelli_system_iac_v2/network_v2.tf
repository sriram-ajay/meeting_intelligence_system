# =============================================================================
# V2 Private Networking — subnets, route table, VPC endpoints, security groups
#
# V2 ECS tasks run in private subnets with NO public IPs.
# AWS service access is via VPC endpoints.
# Internet access (OpenAI API) is via fck-nat NAT instance in public subnet.
# =============================================================================

# --- Private Subnets (V2 owns these) ---

resource "aws_subnet" "private" {
  count                   = 2
  vpc_id                  = data.aws_vpc.main.id
  cidr_block              = "10.0.${count.index + 3}.0/24" # 10.0.3.0/24, 10.0.4.0/24
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.project_name}-private-subnet-${count.index}"
  }
}

# --- Private Route Table (no internet route — endpoints only) ---

resource "aws_route_table" "private" {
  vpc_id = data.aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-private-rt"
  }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# --- ECS Security Group (V2 owns — allows inbound from V1 ALB SG) ---

resource "aws_security_group" "ecs_v2" {
  name        = "${var.project_name}-ecs-sg"
  description = "V2 ECS tasks - allow inbound from ALB"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    description     = "API from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [data.aws_security_group.lb_sg.id]
  }

  ingress {
    description     = "UI from ALB"
    from_port       = 8501
    to_port         = 8501
    protocol        = "tcp"
    security_groups = [data.aws_security_group.lb_sg.id]
  }

  ingress {
    description = "API from ECS tasks (service-to-service)"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    self        = true
  }

  egress {
    description = "All outbound (endpoints + inter-service)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-ecs-sg"
  }
}

# --- VPC Endpoint Security Group (allow HTTPS from V2 ECS SG) ---

resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.project_name}-vpce-sg"
  description = "Allow HTTPS from V2 ECS tasks to VPC endpoints"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    description     = "HTTPS from V2 ECS"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_v2.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-vpce-sg"
  }
}

# =============================================================================
# Gateway Endpoints (FREE — route-table based)
# =============================================================================

# S3 Gateway — raw, derived buckets + ECR image layers
# Attach to BOTH public (V1 still uses) and private route tables
resource "aws_vpc_endpoint" "s3" {
  vpc_id       = data.aws_vpc.main.id
  service_name = "com.amazonaws.${var.aws_region}.s3"

  route_table_ids = [
    aws_route_table.private.id,
  ]

  tags = {
    Name = "${var.project_name}-s3-gw"
  }
}

# DynamoDB Gateway — MeetingsMetadata table
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id       = data.aws_vpc.main.id
  service_name = "com.amazonaws.${var.aws_region}.dynamodb"

  route_table_ids = [
    aws_route_table.private.id,
  ]

  tags = {
    Name = "${var.project_name}-dynamodb-gw"
  }
}

# =============================================================================
# Interface Endpoints (~$7.20/mo each — ENI-based, AZ-a only for Phase 1)
# =============================================================================

# ECR API — container image manifest lookups
resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = data.aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids         = [aws_subnet.private[0].id] # AZ-a only (Phase 1)
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project_name}-ecr-api"
  }
}

# ECR Docker — docker image layer pulls
resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = data.aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids         = [aws_subnet.private[0].id]
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project_name}-ecr-dkr"
  }
}

# CloudWatch Logs — awslogs driver ships stdout/stderr
resource "aws_vpc_endpoint" "logs" {
  vpc_id              = data.aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids         = [aws_subnet.private[0].id]
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project_name}-logs"
  }
}

# Bedrock Runtime — LLM + embedding invocations
resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = data.aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids         = [aws_subnet.private[0].id]
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project_name}-bedrock-runtime"
  }
}

# Secrets Manager — OpenAI API key resolution
resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = data.aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids         = [aws_subnet.private[0].id]
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project_name}-secretsmanager"
  }
}

# ECS — API service calls RunTask to launch ingestion worker
resource "aws_vpc_endpoint" "ecs" {
  vpc_id              = data.aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.ecs"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids         = [aws_subnet.private[0].id]
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project_name}-ecs"
  }
}

# S3 Vectors — vector bucket for embeddings + ANN search
resource "aws_vpc_endpoint" "s3vectors" {
  vpc_id              = data.aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.s3vectors"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true

  subnet_ids         = [aws_subnet.private[0].id]
  security_group_ids = [aws_security_group.vpc_endpoints.id]

  tags = {
    Name = "${var.project_name}-s3vectors"
  }
}

# =============================================================================
# NAT Instance (fck-nat) — cheapest outbound internet for private subnets
# Needed for OpenAI API calls since Titan v2 embeddings are unavailable.
# ~$3.50/month (t3.nano) vs $32/month (NAT Gateway)
# =============================================================================

resource "aws_security_group" "nat" {
  name        = "${var.project_name}-nat-sg"
  description = "NAT instance - allow outbound internet from private subnets"
  vpc_id      = data.aws_vpc.main.id

  # Inbound: all traffic from V2 private subnets
  ingress {
    description     = "All from V2 ECS tasks"
    from_port       = 0
    to_port         = 0
    protocol        = "-1"
    security_groups = [aws_security_group.ecs_v2.id]
  }

  # Outbound: internet
  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-nat-sg"
  }
}

# fck-nat AMI — lightweight AL2023-based NAT instance
data "aws_ami" "fck_nat" {
  most_recent = true
  owners      = ["568608671756"] # fck-nat official

  filter {
    name   = "name"
    values = ["fck-nat-al2023-hvm-*-x86_64-ebs"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

resource "aws_instance" "nat" {
  ami                         = data.aws_ami.fck_nat.id
  instance_type               = "t3.nano"
  subnet_id                   = sort(data.aws_subnets.public.ids)[0] # eu-west-2a public subnet
  associate_public_ip_address = true
  source_dest_check           = false # Required for NAT

  vpc_security_group_ids = [aws_security_group.nat.id]

  tags = {
    Name    = "${var.project_name}-nat"
    Project = var.project_name
  }
}

# Route all internet traffic from private subnets via NAT instance
resource "aws_route" "nat_internet" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  network_interface_id   = aws_instance.nat.primary_network_interface_id
}
