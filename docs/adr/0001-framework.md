# ADR 0001 — Framework web: FastAPI

## Contexto

O desafio pede uma API REST com um endpoint que aceita parâmetros de filtro, precisa de alta disponibilidade sob tráfego em rajada (o volume de jobs Spark varia muito ao longo do dia), e requer documentação do endpoint. Nenhum framework é exigido — a escolha e o racional ficam a critério de quem implementa.

## Decisão

FastAPI + uvicorn.

## Por quê

1. **Assíncrono (ASGI)**: o trabalho de cada requisição é uma leitura em memória (ver ADR 0002 — sem banco de dados), então o gargalo sob rajada nunca é CPU, é a capacidade de aceitar muitas conexões simultâneas. Um modelo assíncrono lida com isso sem precisar de uma thread ou processo por requisição.

2. **Validação automática de parâmetros**: os filtros de tipo de instância (`instance_family`, `instance_type`, `az`) são declarados como type hints do Python e validados pelo Pydantic sem código manual de parsing.

3. **Documentação automática**: toda rota FastAPI gera uma página Swagger em `/docs`, satisfazendo o requisito de documentação do endpoint sem um artefato separado para manter sincronizado.

## Alternativas avaliadas

- **Flask**: WSGI síncrono, exigiria um servidor de aplicação com múltiplos workers/threads para atingir concorrência equivalente, e validação de parâmetros manual ou via extensão (`flask-pydantic`). Mais trabalho para o mesmo resultado.
- **Litestar**: framework mais recente, arquitetura em alguns pontos mais limpa e benchmarks de performance ligeiramente melhores que o FastAPI. Não escolhido porque FastAPI tem adoção e familiaridade muito maiores — qualquer engenheiro do time consegue manter o código sem curva de aprendizado adicional. Essa é a troca consciente: familiaridade da comunidade em vez de uma vantagem marginal de performance.
