terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "us-east-1"
}

variable "image" {
  description = "Container image URI for the ECS Fargate service"
  type        = string
}

variable "db_engine_version" {
  description = "PostgreSQL engine version for RDS"
  type        = string
  default     = "15.4"
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.common_tags
  }
}

locals {
  environment  = "staging"
  region       = var.region
  service_name = "deploy-ecs"

  common_tags = {
    Project     = "infra-agent"
    ManagedBy   = "terraform"
    Environment = local.environment
  }
}

module "ecs_fargate" {
  source = "./terraform/modules/ecs-fargate"

  service_name = local.service_name
  image        = var.image
  cpu          = 512
  memory       = 1024
  min_tasks    = 1
  max_tasks    = 4
  environment  = local.environment
}

module "rds_postgres" {
  source = "./terraform/modules/rds-postgres"

  identifier     = "${local.service_name}-${local.environment}"
  instance_class = "db.t3.micro"
  engine_version = var.db_engine_version
  multi_az       = false
  environment    = local.environment
}

module "cloudwatch_alarms" {
  source = "./terraform/modules/cloudwatch-alarms"

  service_name      = local.service_name
  ecs_cluster_name  = module.ecs_fargate.cluster_name
  environment       = local.environment
}

output "service_url" {
  description = "ALB DNS name for the ECS Fargate service"
  value       = module.ecs_fargate.alb_dns_name
}

output "db_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = module.rds_postgres.endpoint
  sensitive   = true
}