# Architecture Decision Records

Cada arquivo aqui documenta uma decisão arquitetural: o problema que a motivou, a escolha feita, o racional técnico e as alternativas consideradas. Formato leve — contexto, decisão, porquê, alternativas — sem o overhead de um template pesado.

| ADR | Decisão |
|---|---|
| [0001](./0001-framework.md) | Framework web: FastAPI |
| [0002](./0002-sem-banco-de-dados.md) | Nenhum banco de dados |
| [0003](./0003-algoritmo-scoring.md) | Algoritmo de scoring: sistema de pontos |
| [0004](./0004-topologia-aws.md) | Topologia de produção: ECS Fargate, não Lambda |
| [0005](./0005-demonstracao-local-sem-conta-aws.md) | Demonstrar comportamento AWS-dependente sem conta AWS |
| [0006](./0006-get-pool-vs-get-pools.md) | Ambiguidade `/get-pool` vs `/get-pools` |
| [0007](./0007-terraform-desacoplado-do-deploy.md) | Terraform desacoplado da esteira de deploy |
