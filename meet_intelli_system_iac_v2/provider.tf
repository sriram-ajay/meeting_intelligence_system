# =============================================================================
# V2 Terraform Provider — Completely isolated from V1 state
# =============================================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  backend "s3" {
    bucket  = "meeting-intel-terraform-state-637423277250"
    key     = "meeting-intel-v2/terraform.tfstate" # Separate key from V1
    region  = "eu-west-2"
    encrypt = true
  }
}

provider "aws" {
  region      = var.aws_region
  max_retries = 3
}
