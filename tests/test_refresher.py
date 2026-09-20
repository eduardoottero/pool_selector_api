"""Testes do loop de ingestão: cache incremental, resiliência a linha
malformada e a falha de fonte, e a publicação periódica do snapshot.
"""

import asyncio

import pytest

from app.core.config import Settings
from app.core.snapshot import SnapshotStore
from app.domain.events import Status
from app.ingestion.refresher import EventCache, build_snapshot, refresh_loop
from app.ingestion.sources import LocalFileEventSource


def _write_event_file(tmp_path, name, lines):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n")
    return path


def _valid_event_line(pool_id="pool-r6.xlarge-us-east-1a", status="SUCCESS"):
    import json
    from datetime import UTC, datetime

    return json.dumps(
        {
            "finished_at": datetime.now(UTC).isoformat(),
            "job_id": "test-job",
            "pool_id": pool_id,
            "status": status,
            "reason": None,
        }
    )


# --- EventCache --------------------------------------------------------------


def test_cache_parses_valid_lines_into_events(tmp_path):
    _write_event_file(tmp_path, "10.jsonl", [_valid_event_line()])
    source = LocalFileEventSource(tmp_path)
    cache = EventCache()

    ref = source.list_objects()[0]
    events = cache.get_or_parse(ref, source)

    assert len(events) == 1
    assert events[0].status == Status.SUCCESS


def test_cache_skips_malformed_lines_without_crashing(tmp_path):
    _write_event_file(
        tmp_path,
        "10.jsonl",
        [_valid_event_line(), "isto não é json válido", '{"campo_errado": true}'],
    )
    source = LocalFileEventSource(tmp_path)
    cache = EventCache()

    ref = source.list_objects()[0]
    events = cache.get_or_parse(ref, source)

    assert len(events) == 1  # só a linha válida
    assert cache.malformed_count == 2  # json inválido + schema inválido


def test_cache_skips_blank_lines(tmp_path):
    _write_event_file(tmp_path, "10.jsonl", [_valid_event_line(), "", "   "])
    source = LocalFileEventSource(tmp_path)
    cache = EventCache()

    ref = source.list_objects()[0]
    events = cache.get_or_parse(ref, source)

    assert len(events) == 1
    assert cache.malformed_count == 0  # linha em branco não é malformada, é ignorada


def test_cache_reuses_parsed_events_when_version_unchanged(tmp_path):
    _write_event_file(tmp_path, "10.jsonl", [_valid_event_line()])
    source = LocalFileEventSource(tmp_path)
    cache = EventCache()
    ref = source.list_objects()[0]

    events1 = cache.get_or_parse(ref, source)
    events2 = cache.get_or_parse(ref, source)  # mesma versão, deveria vir do cache

    assert events1 is events2  # mesma lista, não reparseada


def test_cache_reparses_when_version_changes(tmp_path):
    import os
    import time

    path = _write_event_file(tmp_path, "10.jsonl", [_valid_event_line()])
    source = LocalFileEventSource(tmp_path)
    cache = EventCache()
    ref1 = source.list_objects()[0]
    cache.get_or_parse(ref1, source)

    time.sleep(0.01)
    os.utime(path, (time.time() + 10, time.time() + 10))
    path.write_text(_valid_event_line() + "\n" + _valid_event_line() + "\n")

    ref2 = source.list_objects()[0]
    events2 = cache.get_or_parse(ref2, source)

    assert len(events2) == 2  # reparseado, agora com 2 eventos


def test_cache_forget_stale_removes_objects_no_longer_present(tmp_path):
    _write_event_file(tmp_path, "10.jsonl", [_valid_event_line()])
    source = LocalFileEventSource(tmp_path)
    cache = EventCache()
    ref = source.list_objects()[0]
    cache.get_or_parse(ref, source)

    assert ref.key in cache._cache

    cache.forget_stale(current_keys=set())  # simula o objeto tendo desaparecido

    assert ref.key not in cache._cache


# --- build_snapshot ------------------------------------------------------


def test_build_snapshot_aggregates_events_into_stats(tmp_path):
    _write_event_file(tmp_path, "10.jsonl", [_valid_event_line() for _ in range(5)])
    source = LocalFileEventSource(tmp_path)
    cache = EventCache()
    settings = Settings()

    snapshot = build_snapshot(source, cache, settings)

    assert "pool-r6.xlarge-us-east-1a" in snapshot.stats
    assert snapshot.total_events_considered == 5
    assert snapshot.malformed_events == 0


def test_build_snapshot_empty_source_returns_empty_stats(tmp_path):
    source = LocalFileEventSource(tmp_path / "vazio")
    cache = EventCache()
    settings = Settings()

    snapshot = build_snapshot(source, cache, settings)

    assert snapshot.stats == {}
    assert snapshot.total_events_considered == 0


# --- refresh_loop (async) -------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_loop_publishes_a_snapshot_on_first_iteration(tmp_path):
    _write_event_file(tmp_path, "10.jsonl", [_valid_event_line()])
    source = LocalFileEventSource(tmp_path)
    store = SnapshotStore()
    settings = Settings(refresh_interval_seconds=60)  # alto o bastante para 1 ciclo só
    stop_event = asyncio.Event()

    async def stop_after_first_publish():
        # espera o primeiro ciclo publicar algo, então sinaliza parada
        while store.current.total_events_considered == 0:
            await asyncio.sleep(0.01)
        stop_event.set()

    await asyncio.wait_for(
        asyncio.gather(
            refresh_loop(source, store, settings, stop_event=stop_event),
            stop_after_first_publish(),
        ),
        timeout=5,
    )

    assert store.current.total_events_considered == 1


@pytest.mark.asyncio
async def test_refresh_loop_survives_a_failing_source():
    """Uma fonte que sempre levanta exceção não deve travar o loop nem
    impedir que ele seja parado — a API continua servindo o snapshot vazio
    anterior em vez de cair."""

    class BrokenSource:
        def list_objects(self):
            raise ConnectionError("fonte indisponível")

        def read_lines(self, ref):
            raise ConnectionError("fonte indisponível")

    store = SnapshotStore()
    settings = Settings(refresh_interval_seconds=60)
    stop_event = asyncio.Event()

    async def stop_soon():
        await asyncio.sleep(0.05)
        stop_event.set()

    await asyncio.wait_for(
        asyncio.gather(
            refresh_loop(BrokenSource(), store, settings, stop_event=stop_event),
            stop_soon(),
        ),
        timeout=5,
    )

    # não travou, não propagou a exceção, e o snapshot continua o vazio inicial
    assert store.current.stats == {}
