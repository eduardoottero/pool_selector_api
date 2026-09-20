provider "aws" {
  region = var.aws_region
}

module "api" {
  source = "../../modules/api"

  environment                = "prod"
  aws_region                 = var.aws_region
  vpc_id                     = var.vpc_id
  subnet_ids                 = var.subnet_ids
  container_image            = var.container_image
  s3_events_bucket_name      = var.s3_events_bucket_name
  desired_count              = 3   # >=2 AZs cobertas + margem para um pico sem esperar o autoscaling reagir
  task_cpu                   = 512 # 0.5 vCPU — volume de produção justifica mais headroom
  task_memory                = 1024
  log_retention_days         = 30   # retenção maior para investigação de incidentes
  enable_deletion_protection = true # nunca remover o ALB de prod por engano
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "container_image" {
  type = string
}

variable "s3_events_bucket_name" {
  type    = string
  default = "pool-selector-api-events-prod"
}
