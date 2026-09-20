"""Testes do snapshot imutável e da troca atômica de ponteiro."""

from datetime import UTC, datetime, timedelta

from app.core.snapshot import EMPTY_SNAPSHOT, RankingSnapshot, SnapshotStore


def test_empty_snapshot_has_no_pools():
    assert EMPTY_SNAPSHOT.stats == {}
    assert EMPTY_SNAPSHOT.total_events_considered == 0


def test_snapshot_store_starts_with_empty_snapshot():
    store = SnapshotStore()
    assert store.current.stats == {}


def test_publish_replaces_the_current_snapshot():
    store = SnapshotStore()
    new_snapshot = RankingSnapshot(
        stats={}, built_at=datetime.now(UTC), malformed_events=0, total_events_considered=5
    )

    store.publish(new_snapshot)

    assert store.current is new_snapshot
    assert store.current.total_events_considered == 5


def test_age_seconds_reflects_time_since_built_at():
    old_snapshot = RankingSnapshot(
        stats={},
        built_at=datetime.now(UTC) - timedelta(seconds=90),
        malformed_events=0,
        total_events_considered=0,
    )
    assert old_snapshot.age_seconds >= 90


def test_snapshot_is_immutable():
    """Um snapshot frozen não pode ser alterado depois de criado — é o que
    garante que requisições concorrentes nunca vejam um estado parcial."""
    snapshot = RankingSnapshot(
        stats={}, built_at=datetime.now(UTC), malformed_events=0, total_events_considered=0
    )
    try:
        snapshot.total_events_considered = 999  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised, "esperava que a atribuição num dataclass frozen levantasse um erro"
