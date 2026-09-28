# ADR 0003 — Algoritmo de scoring: sistema de pontos

## Contexto

O endpoint precisa ranquear pools por probabilidade de reter capacidade spot. O schema de eventos separa falha por `SPOT_INSTANCE_TERMINATION` (sinal de disponibilidade da AZ) de `TIMED_OUT`/`SPARK_EXECUTION_ERROR` (sinal de qualidade do job, não do pool). Qualquer amostra pequena precisa de correção para não vencer por sorte contra um pool com muito mais histórico, e a resposta é consumida sob rajada — recomendar sempre o mesmo pool cria efeito manada, concentrando tráfego exatamente na AZ que a recomendação deveria proteger.

## Decisão

Sistema de pontos aritmético: peso por idade do evento (3/2/1, em degraus), 
classificação em bom/ruim/ignorado, nota = `(bom + 5) / (bom + ruim + 10)`, 
sorteio ponderado entre os 3 melhores pools. Nenhuma fórmula estatística.

## Limitações assumidas (documentadas, não escondidas)

- **Degraus nas bordas das janelas de idade.** Um evento de 5h59 pesa 2; um de 6h01 pesa 1. Não existe transição suave — é uma aproximação em degraus de uma curva contínua de decaimento.
- **Baixa resolução entre pools igualmente bons.** Dois pools saudáveis terminam com notas próximas. Aceitável porque o sorteio já trata ambos como bons candidatos de qualquer forma.

## Evidência (números reais do dataset sintético)

| Pool | Amostra | Nota ingênua | Nota do sistema de pontos |
|---|---|---|---|
| `r6.xlarge-us-east-1a` (workhorse) | 424 eventos, 97% sucesso | 0,97 | **0,96** (#1 do ranking) |
| `r6.2xlarge-us-east-1d` (novato sortudo) | 2 eventos, 100% sucesso | 1,00 | **0,67** (último do ranking) |

Sem a correção, o novato sortudo venceria o workhorse por ter uma taxa ingênua maior — exatamente o problema que este algoritmo existe para evitar.
