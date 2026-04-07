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
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  description = "VPC ID where resources will be deployed"
  type        = string
}

variable "private_subnets" {
  description = "List of private subnet IDs"
  type        = list(string)
}

variable "public_subnets" {
  description = "List of public subnet IDs"
  type        = list(string)
}

variable "container_image" {
  description = "Container image URI for the ECS Fargate service"
  type        = string
}

variable "database_name" {
  description = "Name of the PostgreSQL database"
  type        = string
  default     = "testapi"
}

variable "postgres_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "15.4"
}

provider "aws" {
  region = var.region
}

locals {
  environment  = "staging"
  service_name = "test-api"
  region       = var.region

  common_tags = {
    Project     = "infra-agent"
    ManagedBy   = "terraform"
    Environment = local.environment
  }
}

module "ecs_fargate" {
  source = "github.com/securedpress/aws-terraform-modules//modules/ecs-fargate?ref=v1.1.0"

  service_name    = local.service_name
  image           = var.container_image
  cpu             = 512
  memory          = 1024
  min_tasks       = 1
  max_tasks       = 4
  environment     = local.environment
  vpc_id          = var.vpc_id
  private_subnets = var.private_subnets
  public_subnets  = var.public_subnets
}

module "rds_postgres" {
  source = "github.com/securedpress/aws-terraform-modules//modules/rds-postgres?ref=v1.1.0"

  identifier                = "${local.service_name}-${local.environment}"
  instance_class            = "db.t3.micro"
  engine_version            = var.postgres_engine_version
  multi_az                  = false
  environment               = local.environment
  vpc_id                    = var.vpc_id
  private_subnets           = var.private_subnets
  allowed_security_group_ids = [module.ecs_fargate.service_security_group_id]
  database_name             = var.database_name
}

module "cloudwatch_alarms" {
  source = "github.com/securedpress/aws-terraform-modules//modules/cloudwatch-alarms?ref=v1.1.0"

  service_name       = local.service_name
  ecs_cluster_name   = module.ecs_fargate.cluster_name
  db_instance_id     = module.rds_postgres.db_instance_id
  environment        = local.environment
  enable_remediation = false
}

output "service_url" {
  description = "ALB DNS name for the ECS Fargate service"
  value       = module.ecs_fargate.alb_dns_name
}

output "db_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = module.rds_postgres.db_endpoint
  sensitive   = true
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = module.ecs_fargate.cluster_name
}

output "db_instance_id" {
  description = "RDS instance identifier"
  value       = module.rds_postgres.db_instance_id
}