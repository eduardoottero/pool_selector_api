# ADR 0002 — Nenhum banco de dados

## Contexto

O desafio não exige uso de banco de dados (SQL ou NoSQL) — pede que a escolha, incluindo a de não usar nenhum, seja justificada. O estado que a API precisa servir é um ranking agregado por pool, recalculado periodicamente a partir dos eventos do S3 (ver ADR 0003 para o algoritmo).

## Decisão

Nenhum banco de dados. O ranking vive inteiramente em memória, num `RankingSnapshot` imutável (`app/core/snapshot.py`), recalculado por um loop de background (`app/ingestion/refresher.py`) e publicado via troca atômica de referência.

## Por quê

O estado é **derivado, não autoritativo** — o S3 é a fonte da verdade, e o snapshot inteiro pode ser reconstruído a partir dele em segundos. O volume de dados também é pequeno: algumas dezenas de pools, cada um com quatro números (pontos bons, pontos ruins, eventos ignorados, eventos totais) — poucos kilobytes no total, independente de quantos eventos brutos existam no histórico.

Introduzir um banco (Redis, DynamoDB) adicionaria um hop de rede no caminho quente da requisição, uma nova superfície de falha, e custo operacional — para proteger um dado que não precisa de durabilidade nem de consistência entre instâncias.

## O trade-off aceito, e por que ele é aceitável aqui

Cada instância do processo mantém sua própria cópia do snapshot. Durante o intervalo entre dois ciclos de refresh (60s por padrão), duas instâncias podem responder com rankings ligeiramente diferentes. Para uma recomendação usada como *dica* de balanceamento — não uma trava de concorrência nem uma transação financeira — essa leve divergência é aceitável, e tem um efeito colateral positivo: snapshots levemente diferentes entre instâncias, somados ao sorteio anti-manada (ADR 0003), fazem as instâncias descorrelacionarem suas recomendações, reduzindo ainda mais o risco de uma rajada concentrar tráfego num único pool.

## Quando isso mudaria

- **Redis**: se fosse necessário um rate-limit rígido e compartilhado entre instâncias (ex.: "no máximo N recomendações deste pool por minuto, contado globalmente").
- **DynamoDB**: se o cálculo do snapshot ficasse caro demais para repetir em cada instância, justificando um único processo escritor publicando para todos os leitores.
- **DuckDB**: se o volume de eventos brutos crescesse a ponto de a agregação em Python puro (ver `app/core/scoring.py`) se tornar o gargalo — DuckDB lê JSONL/Parquet do S3 nativamente e agrega em C++, seria o próximo passo natural de escala na camada de ingestão.

Nenhum desses gatilhos se aplica ao volume e ao caso de uso atuais.
