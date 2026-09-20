# Imagem de produção da API — usada pelo CI (build de validação) e pela
# esteira de deploy (Etapa 6). Não é o caminho padrão de desenvolvimento
# local (ver Makefile: `make dev` usa Poetry direto, sem Docker), mas
# precisa existir e estar correta porque é o artefato que de fato roda em
# produção.

FROM python:3.12-slim AS base

# variáveis padrão de higiene para containers Python:
# - não grava .pyc (não precisa persistir cache de bytecode numa imagem efêmera)
# - saída sem buffer, para os logs aparecerem em tempo real no `docker logs`
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# instala o Poetry antes de copiar o código: assim o cache de camadas do
# Docker só invalida esta etapa se a versão do Poetry mudar, não a cada
# alteração de código
RUN pip install --no-cache-dir poetry==2.2.1

# copia só os arquivos de dependência primeiro — outra otimização de cache:
# `poetry install` só é re-executado quando pyproject.toml/poetry.lock mudam,
# não a cada mudança em app/
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

COPY app ./app

EXPOSE 5050

# --host 0.0.0.0: precisa escutar em todas as interfaces dentro do
# container, não só localhost, para o mapeamento de porta do Docker
# (-p 5050:5050) conseguir alcançar o processo
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5050"]
