# Outputs consumidos pelo workflow de deploy (.github/workflows/deploy-*.yml)
# via `vars` do GitHub — é o único ponto de acoplamento entre a camada de
# provisionamento (aqui) e a de deploy da aplicação. Ver
# docs/adr/0006-terraform-desacoplado.md.

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  value = aws_ecs_service.api.name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "alb_dns_name" {
  value = aws_lb.api.dns_name
}

output "s3_events_bucket" {
  value = aws_s3_bucket.events.bucket
}
