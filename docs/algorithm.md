# Algoritmo de scoring

O racional completo da escolha (por que este algoritmo, e não um
estimador estatístico) está em [`docs/adr/0003-algoritmo-scoring.md`](./adr/0003-algoritmo-scoring.md).
Este documento explica o algoritmo em si, passo a passo, com números
reais do dataset sintético do projeto.

## A pergunta que o algoritmo responde

Não é "qual pool teve mais sucessos historicamente" — é "qual pool tem
menor chance de perder capacidade spot na próxima execução". O schema de
eventos permite separar essas duas perguntas: só o motivo
`SPOT_INSTANCE_TERMINATION` é sinal de disponibilidade da AZ.
`TIMED_OUT` e `SPARK_EXECUTION_ERROR` dizem que o *job* falhou por conta
própria — não que o *pool* estava indisponível.

## Passo 1 — peso por idade do evento

| Idade do evento | Peso | Env var |
|---|---|---|
| < 1h (`WINDOW_RECENT_H`) | 3 (`WEIGHT_RECENT`) | recente |
| 1h – 6h (`WINDOW_MID_H`) | 2 (`WEIGHT_MID`) | intermediário |
| 6h – 12h (`LOOKBACK_HOURS`) | 1 (`WEIGHT_OLD`) | antigo |
| > 12h | 0 (descartado) | fora da janela |

Um evento de uma hora atrás pesa 3x mais que um evento entre 6-12h atrás.
É assim que a API reage a uma AZ que piorou "só agora", em vez de diluir
o sinal na média de um dia inteiro. A janela total (`LOOKBACK_HOURS=12`)
foi calibrada — não é o primeiro valor tentado — para ficar próxima da
escala de tempo em que a disponibilidade de spot de fato muda; ver a nota
de calibração no fim deste documento.

## Passo 2 — classificação em bom / ruim / ignorado

| status | reason | classe | função |
|---|---|---|---|
| `SUCCESS` | qualquer | **bom** | `classify_event` → `"good"` |
| `FAILED` | `SPOT_INSTANCE_TERMINATION` | **ruim** | `classify_event` → `"bad"` |
| `FAILED` | `TIMED_OUT` | **ignorado** | `classify_event` → `"ignored"` |
| `FAILED` | `SPARK_EXECUTION_ERROR` | **ignorado** | `classify_event` → `"ignored"` |

Eventos ignorados não entram no denominador da nota — mas são contados e
expostos em `stats.ignored_events` na resposta, como diagnóstico.

## Passo 3 — a nota, com pontos de cortesia

```
score = (good_points + COURTESY_POINTS) / (good_points + bad_points + 2 × COURTESY_POINTS)
```

Com `COURTESY_POINTS = 5` (o default), todo pool começa como se já tivesse
5 pontos bons e 5 pontos ruins fictícios. Isso resolve dois problemas com
uma única fórmula:

- **Amostra pequena não vence por sorte.** Um pool com 2 sucessos e 0
  falhas tem taxa ingênua de 100%, mas nota `(2+5)/(2+10) = 0,58` — não
  suficiente para vencer um pool com histórico maior e taxa real alta.
- **Cold start sem passo separado.** Um pool sem nenhum evento dá
  `(0+5)/(0+10) = 0,50` automaticamente — elegível, nem favorecido nem
  excluído.

## Passo 4 — sorteio entre os melhores (anti-manada)

```python
candidates = rank(stats)[:TOP_K]          # TOP_K = 3 por padrão
chosen = random.choices(candidates, weights=[c.score for c in candidates])[0]
```

Um `argmax` determinístico devolveria sempre o mesmo pool para toda
requisição — sob uma rajada de centenas de jobs simultâneos, isso
concentraria todo o tráfego numa única AZ, esgotando exatamente a
capacidade que a tornava a melhor escolha. O sorteio ponderado espalha a
carga entre os melhores candidatos, proporcionalmente à confiança em cada
um.

`?strategy=argmax` existe como escape hatch determinístico, útil para
depuração e para os testes automatizados que precisam de reprodutibilidade.

## Evidência: números reais do dataset sintético

Gerado por `poetry run python -m app.tools.generate_events` (seed 42, 48h)
e processado por `compute_stats`:

| Pool | Cenário | Amostra | Taxa ingênua | Nota do algoritmo | Posição |
|---|---|---|---|---|---|
| `r6.xlarge-us-east-1a` | workhorse confiável | 172 eventos ponderados | 97% | **0,960** | **#1 / 27** |
| `r6.2xlarge-us-east-1d` | novato sortudo | 2 eventos, ambos sucesso | 100% | **0,667** | **#27 / 27** (último) |
| `c6.xlarge-us-east-1b` | job patológico | 84 eventos válidos + 18 ignorados | — | **0,894** | #2 / 27 |
| `r6.xlarge-us-east-1c` | AZ degradando nas últimas 6h | 142 eventos ponderados | — | **0,815** | #13 / 27 |

A comparação mais reveladora: o **novato sortudo tem 100% de taxa
ingênua e perde para o workhorse**, que tem apenas 97%. Sem a correção do
Passo 3, a ordem seria invertida — o algoritmo de fato resolve o problema
que se propõe a resolver, não só na teoria.

O **job patológico** (`c6.xlarge-us-east-1b`) recebeu 18 falhas de
`TIMED_OUT`/`SPARK_EXECUTION_ERROR` de um job especificamente mal
escrito, e ainda assim ficou em #2 do ranking — porque essas falhas nunca
entraram no cálculo.

## Nota de calibração: por que `LOOKBACK_HOURS = 12`, não 24

O valor inicial de 24h foi trocado por 12h depois de uma validação contra
o dataset real revelar um problema de magnitude: com 24h, o efeito do
decaimento no cenário de "AZ degradando" (que perde disponibilidade nas
últimas 6h) ficava diluído por 18h de histórico ainda saudável, e a queda
observada na nota era pequena demais para ser um sinal útil. Reduzir a
janela para 12h — mais próxima da escala de tempo real em que a
disponibilidade de spot muda dentro de um turno de trabalho — triplicou o
efeito observado.

## Parâmetros (todos ajustáveis via env var, sem redeploy)

| Parâmetro | Default | Significado operacional |
|---|---|---|
| `WEIGHT_RECENT` / `WEIGHT_MID` / `WEIGHT_OLD` | 3 / 2 / 1 | Quanto um evento recente pesa mais que um antigo |
| `WINDOW_RECENT_H` / `WINDOW_MID_H` | 1.0 / 6.0 | Bordas das faixas de idade, em horas |
| `LOOKBACK_HOURS` | 12 | Janela de eventos considerada; mais antigo é descartado |
| `COURTESY_POINTS` | 5 | Evidência que um pool novo precisa acumular para ser levado a sério |
| `TOP_K` | 3 | Tamanho do conjunto sobre o qual a carga é sorteada |

Todos expostos em `GET /health` — o valor efetivo em produção é
inspecionável sem acesso ao código-fonte.
