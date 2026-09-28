# Pool Selector API

API REST que seleciona o pool de instâncias EC2 spot com maior probabilidade de um job Spark executar sem perder capacidade, 
a partir do histórico de eventos de finalização de jobs.

## Quickstart

```bash
make dev
```

Um único comando: instala as dependências num ambiente virtual isolado (Poetry), gera um dataset sintético de eventos (determinístico) e sobe a API em `http://localhost:5050`. Não depende de Docker.

```bash
curl http://localhost:5050/get-pools
curl "http://localhost:5050/get-pools?instance_family=r6"
curl http://localhost:5050/health
```

Documentação interativa (Swagger): `http://localhost:5050/docs`.

## O problema e a resposta em uma frase

O endpoint não retorna "o pool com melhor taxa de sucesso histórica" — ele separa falha por indisponibilidade de spot (`SPOT_INSTANCE_TERMINATION`) de falha do próprio job (`TIMED_OUT`, `SPARK_EXECUTION_ERROR`), corrige o viés de amostra pequena, pondera eventos recentes mais que antigos, e sorteia entre os melhores candidatos ao invés de recomendar sempre o mesmo pool — evitando que a própria recomendação sobrecarregue a AZ que a tornou boa. Detalhes e o racional completo em 
[`docs/algorithm.md`](./docs/algorithm.md).

**A prova em números reais do dataset sintético**: um pool com apenas 2 execuções, ambas bem-sucedidas (100% de taxa ingênua), fica em **último** lugar do ranking; um pool com 170+ execuções e 97% de sucesso fica em **primeiro**. Sem a correção de amostra pequena, essa ordem seria invertida.

## Requisitos

- Python 3.12+ (o Makefile fixa a versão automaticamente via Poetry — não é necessário ter o 3.12 "ativo" no shell)
- [Poetry](https://python-poetry.org/) instalado
- Docker, apenas para `make dev-aws` (opcional — ver abaixo)

## Comandos disponíveis

| Comando | O que faz |
|---|---|
| `make dev` | instala, gera dados e sobe o servidor — comando único, sem Docker |
| `make test` | roda a suíte de testes com cobertura |
| `make lint` | ruff (lint + format) e mypy |
| `make verify` | checa que `/health` responde, com o servidor já rodando |
| `make dev-aws` | sobe a API + LocalStack via Docker Compose (S3 real, emulado — precisa do daemon do Docker) |
| `make docker-down` | derruba os containers do `make dev-aws` |
| `make reseed` | força a regeração do dataset sintético |

## Documentação

| Documento | Conteúdo |
|---|---|
| [`docs/algorithm.md`](./docs/algorithm.md) | O algoritmo de scoring, passo a passo, com números reais |
| [`docs/architecture.md`](./docs/architecture.md) | Visão de sistema, fluxo de dados, topologia de produção |
| [`docs/api.md`](./docs/api.md) | Contrato do endpoint, parâmetros, erros, exemplos |
| [`docs/adr/`](./docs/adr/README.md) | Decisões arquiteturais — framework, banco de dados, algoritmo, AWS, CI/CD |
| [`infra/terraform/README.md`](./infra/terraform/README.md) | A topologia AWS como código (nunca aplicada — sem conta AWS) |

## Decisões principais (racional completo nos ADRs)

- **FastAPI**: ASGI casa com o perfil de tráfego em rajada; 
  validação e documentação automática de parâmetros. [ADR 0001](./docs/adr/0001-framework.md)

- **Sem banco de dados**: o estado é derivado do S3, reconstruível em segundos; 
  poucos KB de dados por pool cabem em memória. [ADR 0002](./docs/adr/0002-sem-banco-de-dados.md)

- **Algoritmo de scoring aritmético**, não estatístico: o sorteio final absorve resolução decimal extra, e um cálculo auditável 
  de cabeça responde "por que esse pool?" durante um incidente. [ADR 0003](./docs/adr/0003-algoritmo-scoring.md)

- **ECS Fargate, não Lambda**: o snapshot em memória precisa de um processo de vida longa com loop de background — 
  Lambda   reconstruiria tudo a cada cold start. [ADR 0004](./docs/adr/0004-topologia-aws.md)

- **`make dev` sem Docker**: o comando único não deve depender de um daemon que pode estar parado na máquina de quem avalia.
  [ADR 0005](./docs/adr/0005-demonstracao-local-sem-conta-aws.md)

- **Terraform desacoplado do deploy**: o workflow de deploy só conhece nomes de recursos via variáveis do GitHub, nunca lê um `.tf`.
  [ADR 0007](./docs/adr/0007-terraform-desacoplado-do-deploy.md)

## CI/CD

```
feature/* ──PR──► dev ──► deploy-dev (aprovação manual) ──► abre PR dev→main
                                                                    │
                                                                    ▼
                                            main ──► deploy-prod (aprovação manual)
```

`ci.yml` roda de verdade em todo push/PR — lint, type-check, testes com cobertura, build da imagem Docker e validação do Terraform. Os workflows de deploy são um dry-run honesto (imprimem os comandos reais ao invés de executá-los), guardados por uma variável do repositório — não há conta AWS provisionada para este desafio.

## Testes

```bash
make test
```

72 testes, cobrindo o algoritmo de scoring (com os cenários que provam a correção de amostra pequena e a exclusão de falhas de job), o adapter S3 (via `moto`, sem depender de rede), o loop de ingestão (incluindo resiliência a falha de fonte e linha malformada), e as rotas da API.

## Estrutura do projeto

```
app/
  main.py              # FastAPI + lifespan (liga o loop de ingestão ao processo)
  api/                 # rotas + schemas de request/response
  core/                # scoring (funções puras), config, snapshot em memória
  ingestion/           # fontes de eventos (local/S3) + loop de refresh
  domain/               # modelo de evento, parsing de pool_id
  tools/                # gerador de dados sintéticos, seed do S3
tests/                  # 72 testes
infra/terraform/        # topologia AWS como código (documentada, não aplicada)
.github/workflows/       # CI real + deploy dry-run
docs/                    # arquitetura, algoritmo, API, ADRs
```
