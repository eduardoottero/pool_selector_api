# Topologia de produção descrita em código — validada (fmt/validate) no CI,
# nunca aplicada de verdade (não há conta AWS provisionada para este
# desafio). O racional de cada escolha está em docs/adr/0005-topologia-aws.md.
#
# Fluxo: Route53 -> ALB -> ECS Fargate (a API) -> lê do S3 (bucket de eventos).
# Fargate em vez de Lambda: o snapshot em memória (Etapa 3) precisa de um
# processo de vida longa com um loop de background — Lambda não sustenta
# isso sem reconstruir o snapshot do zero a cada cold start.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  name = "pool-selector-api-${var.environment}"
  tags = {
    Project     = "pool-selector-api"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# --- bucket de eventos (fonte de dados, lida pela API) -----------------------

resource "aws_s3_bucket" "events" {
  bucket = var.s3_events_bucket_name
  tags   = local.tags
}

resource "aws_s3_bucket_versioning" "events" {
  bucket = aws_s3_bucket.events.id
  versioning_configuration {
    status = "Enabled"
  }
}

# --- ECR: repositório da imagem da API ----------------------------------------

resource "aws_ecr_repository" "api" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE" # cada deploy usa uma tag nova (o SHA do commit)
  tags                 = local.tags
}

# --- logs -------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

# --- IAM: a task só pode ler o bucket de eventos, nada além disso -----------

resource "aws_iam_role" "task_execution" {
  name = "${local.name}-task-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name = "${local.name}-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
  tags = local.tags
}

# princípio de menor privilégio: só leitura, só neste bucket
resource "aws_iam_role_policy" "task_s3_read" {
  name = "${local.name}-s3-read"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [aws_s3_bucket.events.arn, "${aws_s3_bucket.events.arn}/*"]
    }]
  })
}

# --- ECS: cluster, task definition, serviço -----------------------------------

resource "aws_ecs_cluster" "this" {
  name = local.name
  tags = local.tags
}

resource "aws_ecs_task_definition" "api" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name  = "api"
    image = var.container_image
    portMappings = [{
      containerPort = 5050
      protocol      = "tcp"
    }]
    environment = [
      { name = "EVENT_SOURCE", value = "s3" },
      { name = "S3_BUCKET", value = aws_s3_bucket.events.bucket },
      { name = "AWS_REGION", value = var.aws_region },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
    # /health reporta a idade do snapshot — uma task cujo refresh_loop
    # travou fica visivelmente não-saudável e sai de rotação no ALB
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:5050/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 10
    }
  }])

  tags = local.tags
}

resource "aws_ecs_service" "api" {
  name            = local.name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = var.subnet_ids
    security_groups = [aws_security_group.api.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 5050
  }

  depends_on = [aws_lb_listener.api]
  tags       = local.tags
}

# --- rede: security group, ALB -----------------------------------------------

resource "aws_security_group" "api" {
  name_prefix = "${local.name}-"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5050
    to_port         = 5050
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_lb" "api" {
  name                       = local.name
  load_balancer_type         = "application"
  subnets                    = var.subnet_ids
  security_groups            = [aws_security_group.alb.id]
  enable_deletion_protection = var.enable_deletion_protection
  tags                       = local.tags
}

resource "aws_lb_target_group" "api" {
  name        = local.name
  port        = 5050
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip" # exigido pelo modo awsvpc do Fargate

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
  }

  tags = local.tags
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# --- autoscaling: reage a picos de tráfego sem intervenção manual -----------

resource "aws_appautoscaling_target" "api" {
  max_capacity       = var.desired_count * 4
  min_capacity       = var.desired_count
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_requests" {
  name               = "${local.name}-scale-on-requests"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.api.arn_suffix}/${aws_lb_target_group.api.arn_suffix}"
    }
    target_value = 1000 # requisições/task/minuto antes de escalar
  }
}
