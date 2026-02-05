terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  backend "s3" {
    bucket  = "meeting-intel-terraform-state-637423277250"
    key     = "meeting-intel/terraform.tfstate"
    region  = "eu-west-2"
    encrypt = true
  }
}

provider "aws" {
  region      = var.aws_region
  max_retries = 3
}
