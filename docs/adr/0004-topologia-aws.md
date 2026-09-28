# ADR 0004 — Topologia de produção: ECS Fargate, não Lambda

## Contexto

O desafio pede que a API seja "pronta para produção" e capaz de absorver picos de tráfego imprevisíveis ao longo do dia sem indisponibilidade. Não há conta AWS provisionada para este projeto — esta topologia é descrita e validada como código 
(ver `infra/terraform/`), nunca aplicada.

## Decisão

ECS Fargate atrás de um Application Load Balancer, com autoscaling por `ALBRequestCountPerTarget`, lendo do S3 via IAM role com permissão apenas de leitura no bucket de eventos.

```
Route53 → ACM/TLS → ALB → ECS Fargate (≥2 AZs) → lê S3 (bucket de eventos)
```

## Por que Fargate e não Lambda

Lambda é a resposta padrão para "tráfego bastante variável ao longo do dia" — mas o design deste projeto tem um detalhe que muda essa conclusão:
o snapshot em memória (ver ADR 0002 e `app/core/snapshot.py`) depende de um processo de vida longa com um loop de background rodando continuamente. Lambda não tem memória durável nem execução em background entre invocações — cada cold start reconstruiria o snapshot do zero a partir do S3, transformando uma consulta de microssegundos numa espera de segundos, exatamente durante o pico de tráfego que a arquitetura tenta absorver. O ponto crítico de latência seria empurrado para dentro do caminho crítico da requisição, não evitado dele.

Com Fargate, o snapshot já está quente nas tasks em execução; o autoscaling adiciona tasks (que herdam o snapshot do próximo ciclo de refresh) enquanto as já ativas continuam servindo. O trade-off aceito:
paga-se por capacidade ociosa nas horas de pouco tráfego, e o scale-out é mais lento que o de Lambda. Mitigado com tasks pequenas (`task_cpu`/`task_memory` baixos, ver `infra/terraform/modules/api/variables.tf`) e headroom suficiente de instâncias mínimas para que o autoscaling nunca precise ser o gate de um pico repentino.

## A variante Lambda, para o registro

Se o padrão de tráfego fosse extremamente espinhoso com longos períodos ociosos, a resposta honesta seria: Lambda + o snapshot num Redis/DynamoDB compartilhado, com uma Lambda agendada separada fazendo a agregação. Essa topologia move o estado do processo para fora dele — exatamente o hop de rede que o ADR 0002 evita no caso atual, mas que se justificaria se o padrão de carga fosse outro.

## Outras peças da topologia

- **ALB com health check em `/health`**: o endpoint reporta a idade do snapshot — uma task cujo `refresh_loop` travou fica visivelmente não-saudável e sai de rotação automaticamente.
- **IAM de menor privilégio**: a task role só tem `s3:GetObject` e `s3:ListBucket`, restritos ao bucket de eventos.
- **CloudWatch Logs** com retenção diferente por ambiente (7 dias em dev, 30 em prod — ver `infra/terraform/README.md`).
