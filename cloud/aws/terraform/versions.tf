terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.69.1"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "edge-cloud-pac"
      ManagedBy = "terraform"
      Phase     = "phase2-validation"
    }
  }
}
