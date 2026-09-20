"""Ponto de entrada da aplicação FastAPI.

O `lifespan` inicia o loop de ingestão (refresh_loop, Etapa 3) como uma task
de background no startup e o sinaliza para parar no shutdown — é o que
mantém o snapshot atualizado durante toda a vida do processo, sem bloquear
a inicialização da API nem exigir um processo separado.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import settings
from app.core.snapshot import snapshot_store
from app.ingestion.refresher import refresh_loop
from app.ingestion.sources import build_event_source


@asynccontextmanager
async def lifespan(app: FastAPI):
    source = build_event_source(settings)
    stop_event = asyncio.Event()
    task = asyncio.create_task(refresh_loop(source, snapshot_store, settings, stop_event))

    yield  # a aplicação atende requisições enquanto o loop roda em paralelo

    stop_event.set()
    await task  # espera o ciclo em andamento terminar antes de finalizar


app = FastAPI(
    title=settings.app_name,
    description="Seleciona o melhor pool de instâncias EC2 spot para jobs Spark",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
