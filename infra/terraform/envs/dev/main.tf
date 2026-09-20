provider "aws" {
  region = var.aws_region
}

module "api" {
  source = "../../modules/api"

  environment                = "dev"
  aws_region                 = var.aws_region
  vpc_id                     = var.vpc_id
  subnet_ids                 = var.subnet_ids
  container_image            = var.container_image
  s3_events_bucket_name      = var.s3_events_bucket_name
  desired_count              = 1   # dev não precisa tolerar perda de AZ
  task_cpu                   = 256 # 0.25 vCPU — carga baixa, custo mínimo
  task_memory                = 512
  log_retention_days         = 7     # não precisa reter log por muito tempo
  enable_deletion_protection = false # facilita destruir/recriar o ambiente
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
  default = "pool-selector-api-events-dev"
}
