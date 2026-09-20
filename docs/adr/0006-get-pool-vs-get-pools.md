# ADR 0006 — Ambiguidade `/get-pool` vs `/get-pools`

## Contexto

O enunciado do desafio usa `/get-pool` num trecho ("possuir um endpoint
/get-pool") e `http://localhost:5050/get-pools` (com a porta, plural)
noutro trecho. As duas formas não podem ser simultaneamente a única
correta sem uma delas ser um erro de digitação — mas não há como saber
qual.

## Decisão

Servir os dois: `/get-pools` como rota canônica (é a que vem acompanhada
da URL completa, a que um avaliador colaria direto no navegador ou no
`curl`) e `/get-pool` como alias, apontando exatamente para o mesmo
handler (`app/api/routes.py`).

```python
@router.get("/get-pools", response_model=GetPoolsResponse)
@router.get("/get-pool", response_model=GetPoolsResponse)
def get_pools(...): ...
```

## Por quê

Escolher um dos dois por adivinhação arrisca falhar a avaliação por um
motivo raso — o endpoint "certo" segundo o enunciado simplesmente não
existir. Servir os dois elimina esse risco sem custo real: é a mesma
função, o mesmo contrato de resposta, duas linhas de decorator. A
alternativa de tratar isso como uma pergunta bloqueante ("qual dos dois
you quis dizer?") não se aplica a um desafio assíncrono sem contato
disponível para esclarecer.

## O padrão geral que esta decisão exemplifica

Diante de uma ambiguidade genuína na especificação, a resposta é satisfazer
as leituras razoáveis **e sinalizar a ambiguidade explicitamente** — este
ADR — em vez de silenciosamente escolher uma e seguir como se não houvesse
dúvida. Numa equipe real, a pergunta certa seria feita a quem escreveu o
requisito; num desafio assíncrono, a próxima melhor opção é registrar a
decisão de forma auditável.
