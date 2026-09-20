# Arquitetura

Visão de sistema. Para o racional de cada decisão individual, ver
[`docs/adr/`](./adr/README.md); para o algoritmo de scoring em detalhe,
[`docs/algorithm.md`](./algorithm.md).

## Visão geral

```
┌──────────────────────────────────────────────────────────────────────┐
│                              Processo da API                          │
│                                                                        │
│   ┌─────────────────┐        ┌──────────────────────────────────┐   │
│   │  refresh_loop    │        │         GET /get-pools           │   │
│   │  (background,    │        │         GET /get-pool  (alias)   │   │
│   │   a cada 60s)     │        │         GET /health              │   │
│   │                  │        │                                  │   │
│   │  1. lista objetos │        │  lê snapshot_store.current       │   │
│   │  2. lê + parseia  │        │  (dict lookup, O(1))             │   │
│   │  3. compute_stats │        │  filtra por instance_type/az     │   │
│   │  4. publica ──────┼───────►│  sorteia entre top-3 (choose_pool)│   │
│   │     snapshot      │        │  responde                        │   │
│   └────────┬─────────┘        └──────────────────────────────────┘   │
│            │                                                          │
└────────────┼──────────────────────────────────────────────────────────┘
             │ EventSource.list_objects() / read_lines()
             ▼
   ┌───────────────────┐         ┌──────────────────────┐
   │ LocalFileEventSource│  ou   │   S3EventSource       │
   │ (padrão, make dev)  │       │ (EVENT_SOURCE=s3)     │
   │ lê data/events/     │       │ boto3 → S3 real ou    │
   │                     │       │ LocalStack (dev-aws)  │
   └───────────────────┘         └──────────────────────┘
```

## O princípio central: cálculo e atendimento são desacoplados

Uma requisição a `/get-pools` nunca lê arquivo, nunca faz parsing, nunca
recalcula nada — é uma consulta a um dicionário já pronto em memória
(`RankingSnapshot`). Todo o trabalho pesado (ler a fonte, parsear JSONL,
agregar por pool) acontece num loop de background separado, que publica
um novo snapshot a cada `REFRESH_INTERVAL_SECONDS` (60s por padrão).

Isso é o que sustenta o requisito de alta disponibilidade sob rajada: o
tempo de resposta de uma requisição não depende do volume de eventos
processados, nem do número de requisições concorrentes.

## Fluxo de dados

1. **Eventos** chegam em formato JSONL, particionados por hora
   (`<data>/<hora>.jsonl`) — um layout que imita como um bucket S3 real
   costuma ser alimentado continuamente (ver `app/tools/generate_events.py`
   para o gerador sintético usado no desenvolvimento).
2. **`EventSource`** (`app/ingestion/sources.py`) abstrai de onde os bytes
   vêm — disco local ou S3 (real ou LocalStack) — atrás da mesma
   interface de dois métodos.
3. **`EventCache`** (`app/ingestion/refresher.py`) faz leitura incremental:
   só reparseia arquivos cujo mtime (local) ou ETag (S3) mudou desde o
   último ciclo.
4. **`compute_stats`** (`app/core/scoring.py`) agrega os eventos parseados
   em `PoolStats` por pool — ver [`docs/algorithm.md`](./algorithm.md).
5. **`RankingSnapshot`** (`app/core/snapshot.py`), imutável, é publicado
   via troca atômica de referência — sem lock, atômica pelo GIL do Python.
6. **A rota** filtra o snapshot pelos parâmetros da requisição e sorteia
   entre os melhores candidatos (`choose_pool`).

## Resiliência

- Uma linha malformada no JSONL é contabilizada e ignorada — nunca
  derruba o ciclo de ingestão inteiro.
- Uma falha ao acessar a fonte (rede fora do ar, bucket inacessível) é
  capturada por ciclo: o snapshot anterior continua sendo servido, e o
  próximo ciclo tenta de novo.
- O `/health` expõe a idade do snapshot — uma task cujo loop travou fica
  visivelmente não-saudável e, em produção, sairia de rotação no ALB (ver
  ADR 0004).

## Topologia de produção (nunca implantada — ver ADR 0004 e 0005)

```
Route53 → ACM/TLS → ALB → ECS Fargate (≥2 AZs) → lê S3 (bucket de eventos)
                              ↑
                    autoscaling por ALBRequestCountPerTarget
```

Descrita como código em [`infra/terraform/`](../infra/terraform/README.md),
validada no CI (`terraform fmt`/`validate`, sem credencial AWS), nunca
aplicada — não há conta AWS provisionada.

## CI/CD

```
feature/* ──PR──► dev ──► deploy-dev (aprovação manual) ──► abre PR dev→main
                                                                    │
                                                                    ▼
                                            main ──► deploy-prod (aprovação manual)
```

`ci.yml` roda de verdade (lint, type-check, testes, build da imagem,
validação do Terraform) em todo push/PR. Os workflows de deploy são um
dry-run honesto, guardado por uma flag do repositório — ver ADR 0007 e
`docs/adr/0007-terraform-desacoplado-do-deploy.md` para o porquê dessa
camada ser desacoplada do provisionamento.

## Estrutura de código

```
app/
  main.py              # FastAPI + lifespan (liga o refresh_loop ao processo)
  api/                 # rotas + schemas de request/response
  core/
    config.py           # todos os parâmetros ajustáveis via env var
    scoring.py           # o algoritmo — funções puras, sem I/O
    snapshot.py          # RankingSnapshot + troca atômica
  ingestion/
    sources.py           # EventSource: adapters local e S3
    refresher.py          # loop de background + cache incremental
  domain/
    events.py            # modelo JobEvent, parsing de pool_id
  tools/
    generate_events.py    # gerador de dados sintéticos
    seed_s3.py             # sobe o dataset local para um bucket S3
```
