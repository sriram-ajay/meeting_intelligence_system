# Terraform Backend Configuration
# Add this to meet_intelli_system_iac/provider.tf after running terraform apply on terraform_backend.tf

# Step 1: Initialize with local backend to create S3 bucket
# terraform init
# terraform apply -target=aws_s3_bucket.terraform_state

# Step 2: Add this backend configuration to provider.tf:
/*
terraform {
  backend "s3" {
    bucket  = "meeting-intel-terraform-state-ACCOUNT_ID"
    key     = "meeting-intel/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}
*/

# Step 3: Run migration:
# terraform init (when prompted, confirm to migrate state to S3)

# Step 4: Verify state is now in S3:
# aws s3 ls s3://meeting-intel-terraform-state-ACCOUNT_ID/
# aws s3 cp s3://meeting-intel-terraform-state-ACCOUNT_ID/meeting-intel/terraform.tfstate . --region us-east-1

# Note: Replace "us-east-1" with your actual AWS_REGION
# Note: Replace "ACCOUNT_ID" with your actual AWS Account ID (available from aws sts get-caller-identity)
# Note: S3 versioning automatically prevents concurrent modifications
