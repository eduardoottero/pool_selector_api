# Variáveis do módulo — os valores concretos vêm dos .tfvars de cada
# ambiente (envs/dev, envs/prod), nunca hardcoded aqui. É isso que faz o
# mesmo módulo servir dev e prod com topologias de capacidade diferentes.

variable "environment" {
  description = "Nome do ambiente (dev, prod) — usado em nomes de recursos e tags."
  type        = string
}

variable "aws_region" {
  description = "Região AWS onde os recursos são provisionados."
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  description = "VPC onde o ALB e as tasks do Fargate rodam."
  type        = string
}

variable "subnet_ids" {
  description = "Subnets (idealmente em pelo menos 2 AZs) para o serviço ECS e o ALB."
  type        = list(string)
}

variable "desired_count" {
  description = "Número de tasks rodando em paralelo. Mais alto em prod para tolerar a perda de uma AZ sem indisponibilidade."
  type        = number
  default     = 1
}

variable "task_cpu" {
  description = "CPU da task Fargate, em unidades de CPU da AWS (1024 = 1 vCPU)."
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Memória da task Fargate, em MB."
  type        = number
  default     = 512
}

variable "container_image" {
  description = "Imagem da API a implantar (ex: <account>.dkr.ecr.<region>.amazonaws.com/pool-selector-api:<tag>)."
  type        = string
}

variable "log_retention_days" {
  description = "Retenção dos logs no CloudWatch. Mais curta em dev para reduzir custo."
  type        = number
  default     = 7
}

variable "enable_deletion_protection" {
  description = "Protege o ALB contra remoção acidental. Só faz sentido ligar em prod."
  type        = bool
  default     = false
}

variable "s3_events_bucket_name" {
  description = "Nome do bucket S3 com os eventos de finalização de job Spark."
  type        = string
}
