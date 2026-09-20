"""Loop de ingestão: lê eventos da fonte configurada, calcula o ranking e
publica um novo snapshot periodicamente.

Roda como uma task assíncrona em background (ver app/main.py, Etapa 4),
iniciada no startup da aplicação. Cada ciclo é independente: uma falha em
um ciclo (fonte indisponível, linha malformada) não derruba o processo —
o snapshot anterior continua sendo servido até o próximo ciclo ter sucesso.
Isso é o que dá à API a resiliência que o requisito de alta disponibilidade
pede: um problema temporário na fonte de dados não tira a API do ar.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from pydantic import ValidationError

from app.core.config import Settings
from app.core.scoring import compute_stats
from app.core.snapshot import RankingSnapshot, SnapshotStore
from app.domain.events import JobEvent
from app.ingestion.sources import EventSource, ObjectRef

logger = logging.getLogger(__name__)


class EventCache:
    """Cache incremental: guarda os eventos já parseados por objeto, para
    não reler e reparsear tudo a cada ciclo do refresher.

    Cada entrada é identificada por (key, version) do ObjectRef. Se a versão
    de um objeto não mudou desde o último ciclo (mtime igual no adapter
    local, ETag igual no S3), os eventos já parseados são reaproveitados —
    só objetos novos ou modificados são lidos e parseados de novo.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, list[JobEvent]]] = {}  # key -> (version, events)
        self.malformed_count = 0

    def get_or_parse(self, ref: ObjectRef, source: EventSource) -> list[JobEvent]:
        cached = self._cache.get(ref.key)
        if cached is not None and cached[0] == ref.version:
            return cached[1]

        events = self._parse_lines(source.read_lines(ref), origin=ref.key)
        self._cache[ref.key] = (ref.version, events)
        return events

    def _parse_lines(self, lines: list[str], origin: str) -> list[JobEvent]:
        events = []
        for line in lines:
            if not line.strip():
                continue
            try:
                events.append(JobEvent(**json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as exc:
                # dado real é sujo: uma linha malformada nunca derruba o
                # loop, só é contabilizada como diagnóstico (exposta em /health)
                self.malformed_count += 1
                logger.warning("evento malformado em %s: %s", origin, exc)
        return events

    def forget_stale(self, current_keys: set[str]) -> None:
        """Remove do cache objetos que não existem mais na fonte (ex.: saíram
        da janela de retenção do bucket), evitando crescimento ilimitado."""
        stale = set(self._cache) - current_keys
        for key in stale:
            del self._cache[key]


def build_snapshot(source: EventSource, cache: EventCache, settings: Settings) -> RankingSnapshot:
    """Executa um ciclo completo: lista objetos, parseia (com cache
    incremental), agrega e devolve um snapshot pronto para publicar."""
    refs = source.list_objects()
    cache.forget_stale({ref.key for ref in refs})

    all_events: list[JobEvent] = []
    for ref in refs:
        all_events.extend(cache.get_or_parse(ref, source))

    now = datetime.now(UTC)
    stats = compute_stats(all_events, now=now)

    return RankingSnapshot(
        stats=stats,
        built_at=now,
        malformed_events=cache.malformed_count,
        total_events_considered=len(all_events),
    )


async def refresh_loop(
    source: EventSource,
    store: SnapshotStore,
    settings: Settings,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Loop infinito (até `stop_event` ser sinalizado): recalcula e publica
    o snapshot a cada `settings.refresh_interval_seconds`.

    `stop_event` existe para permitir parar o loop em testes e no shutdown
    da aplicação, sem depender de matar a task à força.
    """
    cache = EventCache()
    stop_event = stop_event or asyncio.Event()

    while not stop_event.is_set():
        try:
            snapshot = build_snapshot(source, cache, settings)
            store.publish(snapshot)
            logger.info(
                "snapshot publicado: %d pools, %d eventos, %d malformados",
                len(snapshot.stats),
                snapshot.total_events_considered,
                snapshot.malformed_events,
            )
        except Exception:
            # uma fonte indisponível não deve matar o loop nem derrubar a
            # API — o snapshot anterior continua sendo servido normalmente
            logger.exception("falha ao atualizar o snapshot; mantendo o anterior")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.refresh_interval_seconds)
        except TimeoutError:
            pass  # timeout normal: hora de rodar o próximo ciclo
