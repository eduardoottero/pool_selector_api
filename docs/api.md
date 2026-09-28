# API

Documentação interativa completa (gerada automaticamente pelo FastAPI a partir dos schemas em `app/api/schemas.py`): `http://localhost:5050/docs`. Este documento cobre o contrato e os casos de borda em prosa.

## `GET /get-pools` (canônico) / `GET /get-pool` (alias)

O enunciado do desafio usa os dois nomes em trechos diferentes — os dois apontam para o mesmo handler. 
Ver [ADR 0006](./adr/0006-get-pool-vs-get-pools.md).

Devolve o pool recomendado para um job Spark executar, junto com a nota, as estatísticas que embasaram a decisão, e alternativas consideradas.

### Parâmetros de query

| Parâmetro | Tipo | Default | Descrição |
|---|---|---|---|
| `instance_family` | string, repetível | — | Restringe a famílias (ex.: `r6` para memória, `c6` para CPU) |
| `instance_type` | string, repetível | — | Restringe a tipos exatos (ex.: `r6.xlarge`) |
| `az` | string, repetível | — | Restringe a AZs específicas |
| `limit` | int (1–10) | 3 | Quantas alternativas retornar |
| `strategy` | `sample` \| `argmax` | `sample` | `sample` sorteia entre os melhores (anti-manada); `argmax` é determinístico |

`instance_family` cobre o caso de uso descrito no enunciado ("apenas instâncias focadas em memória") sem exigir que quem chama enumere cada tipo; `instance_type` dá controle exato quando necessário.

### Resposta — `200 OK`

```json
{
  "pool_id": "pool-r6.xlarge-us-east-1a",
  "score": 0.96,
  "stats": {
    "good_points": 238.0,
    "bad_points": 5.0,
    "ignored_events": 0,
    "total_events": 172
  },
  "alternatives": [
    {"pool_id": "pool-r6.xlarge-us-east-1a", "score": 0.96},
    {"pool_id": "pool-c6.xlarge-us-east-1b", "score": 0.894},
    {"pool_id": "pool-r6.xlarge-us-east-1d", "score": 0.88}
  ],
  "strategy": "sample",
  "snapshot_age_seconds": 14.1
}
```

`stats` e `alternatives` tornam a decisão inspecionável sem precisar ler o código — ver [`docs/algorithm.md`](./algorithm.md) para o que cada número significa.

### Erros

| Código | Quando | Corpo |
|---|---|---|
| `404` | Nenhum pool no snapshot atende aos filtros informados | `{"detail": "nenhum pool encontrado para os filtros informados (...)"}` |
| `422` | Parâmetro inválido (ex.: `strategy=xyz`) | Erro de validação padrão do FastAPI/Pydantic |
| `503` | O snapshot inicial ainda não foi construído (API acabou de subir) | `{"detail": "nenhum dado de pool disponível ainda — ..."}` |

A distinção entre 404 e 503 é deliberada: 404 diz "seu filtro não tem correspondência", 503 diz "o serviço ainda não está pronto" — sinalizações diferentes que levam a ações diferentes (ajustar o filtro vs. tentar de novo em instantes).

## `GET /health`

```json
{
  "status": "ok",
  "snapshot_age_seconds": 14.1,
  "pools_tracked": 27,
  "total_events_considered": 2010,
  "malformed_events": 0,
  "event_source": "local",
  "parameters": {
    "lookback_hours": 12,
    "weight_recent": 3,
    "weight_mid": 2,
    "weight_old": 1,
    "window_recent_h": 1.0,
    "window_mid_h": 6.0,
    "courtesy_points": 5,
    "top_k": 3,
    "refresh_interval_seconds": 60
  }
}
```

Além de servir como health check (usado pelo ALB em produção, ver ADR 0004), expõe:

- **`snapshot_age_seconds`**: detecta um `refresh_loop` travado antes que vire um problema visível para quem chama `/get-pools`.

- **`malformed_events`**: quantas linhas do JSONL foram descartadas por não corresponderem ao schema — sinal de qualidade de dados na fonte.

- **`parameters`**: os valores efetivos do algoritmo em produção, auditáveis sem acesso ao código nem a um redeploy.

## Exemplos

```bash
# melhor pool, sem restrição
curl http://localhost:5050/get-pools

# apenas famílias focadas em memória
curl "http://localhost:5050/get-pools?instance_family=r6"

# tipo exato, resultado determinístico
curl "http://localhost:5050/get-pools?instance_type=r6.xlarge&strategy=argmax"

# múltiplas famílias e AZs
curl "http://localhost:5050/get-pools?instance_family=r6&instance_family=c6&az=us-east-1a"
```
