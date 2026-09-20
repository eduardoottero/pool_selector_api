# ADR 0003 — Algoritmo de scoring: sistema de pontos

## Contexto

O endpoint precisa ranquear pools por probabilidade de reter capacidade
spot. O schema de eventos separa falha por `SPOT_INSTANCE_TERMINATION`
(sinal de disponibilidade da AZ) de `TIMED_OUT`/`SPARK_EXECUTION_ERROR`
(sinal de qualidade do job, não do pool). Qualquer amostra pequena precisa
de correção para não vencer por sorte contra um pool com muito mais
histórico, e a resposta é consumida sob rajada — recomendar sempre o mesmo
pool cria efeito manada, concentrando tráfego exatamente na AZ que a
recomendação deveria proteger.

## Decisão

Sistema de pontos aritmético: peso por idade do evento (3/2/1, em
degraus), classificação em bom/ruim/ignorado, nota =
`(bom + 5) / (bom + ruim + 10)`, sorteio ponderado entre os 3 melhores
pools. Nenhuma fórmula estatística.

## Por que não Wilson ou suavização de Laplace

Três argumentos técnicos, nenhum por simplicidade:

1. **O sorteio final absorve resolução decimal extra.** Como a saída é um
   sorteio ponderado dentro do conjunto dos melhores candidatos, ganhar
   precisão na quarta casa decimal da nota não muda quem entra nesse
   conjunto nem altera materialmente a distribuição do sorteio. Investir em
   Wilson seria pagar por resolução que a etapa seguinte do próprio
   algoritmo descarta.
2. **Em um sistema com realimentação, a precisão do estimador não é o
   gargalo.** A recomendação muda a carga sobre os pools, que muda os dados
   observados no próximo ciclo — o fator dominante é a defasagem entre
   recomendar e observar o efeito, não o refino estatístico da nota.
3. **Auditabilidade operacional.** Quando um job falhar em produção e
   alguém perguntar "por que a API escolheu esse pool?", um cálculo
   auditável de cabeça responde em minutos — sem precisar explicar um
   intervalo de confiança.

## Limitações assumidas (documentadas, não escondidas)

- **Degraus nas bordas das janelas de idade.** Um evento de 5h59 pesa 2;
  um de 6h01 pesa 1. Não existe transição suave — é uma aproximação em
  degraus de uma curva contínua de decaimento.
- **Baixa resolução entre pools igualmente bons.** Dois pools saudáveis
  terminam com notas próximas. Aceitável porque o sorteio já trata ambos
  como bons candidatos de qualquer forma.

## Alternativas avaliadas

- **Suavização de Laplace** (`(bom + K) / (total + 2K)`): resolve o mesmo
  problema de amostra pequena com uma fórmula ainda mais simples que a
  adotada, mas comprime todas as notas em direção a 0,5, perdendo
  resolução mesmo em pools com muito histórico.
- **Limite inferior de Wilson**: maior resolução perto de 100% de taxa de
  sucesso, que é onde a maior parte dos dados reais vive. Seria o próximo
  passo natural se o ranking precisasse discriminar melhor o topo da lista
  — a interface do algoritmo (`compute_stats` → `PoolStats.score`) não
  mudaria, só a fórmula interna do `score`.

## Evidência (números reais do dataset sintético)

| Pool | Amostra | Nota ingênua | Nota do sistema de pontos |
|---|---|---|---|
| `r6.xlarge-us-east-1a` (workhorse) | 424 eventos, 97% sucesso | 0,97 | **0,96** (#1 do ranking) |
| `r6.2xlarge-us-east-1d` (novato sortudo) | 2 eventos, 100% sucesso | 1,00 | **0,67** (último do ranking) |

Sem a correção, o novato sortudo venceria o workhorse por ter uma taxa
ingênua maior — exatamente o problema que este algoritmo existe para
evitar.
