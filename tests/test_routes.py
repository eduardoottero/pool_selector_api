"""
Testes das rotas /get-pools, /get-pool e /health.

Publica um RankingSnapshot controlado diretamente no snapshot_store antes
de cada teste, ao invés de depender do lifespan real (que dispararia o
refresh_loop lendo data/events do disco) — mais rápido, determinístico, e
isolado do estado real do projeto.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app.core.scoring import PoolStats
from app.core.snapshot import EMPTY_SNAPSHOT, RankingSnapshot, snapshot_store
from app.main import app


def _stats(pool_id, good, bad, ignored=0):
    return PoolStats(
        pool_id=pool_id,
        good_points=good,
        bad_points=bad,
        ignored_events=ignored,
        total_events=good + bad + ignored,
    )


SAMPLE_STATS = {
    "pool-r6.xlarge-us-east-1a": _stats("pool-r6.xlarge-us-east-1a", good=300, bad=5),
    "pool-r6.xlarge-us-east-1c": _stats("pool-r6.xlarge-us-east-1c", good=50, bad=20),
    "pool-c6.xlarge-us-east-1b": _stats("pool-c6.xlarge-us-east-1b", good=100, bad=5, ignored=80),
    "pool-i3.xlarge-us-east-1a": _stats("pool-i3.xlarge-us-east-1a", good=10, bad=1),
}


@pytest.fixture(autouse=True)
def _restore_snapshot_after_test():
    """Garante que o estado do snapshot_store (um singleton de módulo) não
    vaza de um teste para o outro."""
    original = snapshot_store.current
    yield
    snapshot_store.publish(original)


@pytest.fixture
def client_with_sample_snapshot():
    snapshot_store.publish(
        RankingSnapshot(
            stats=SAMPLE_STATS,
            built_at=datetime.now(UTC),
            malformed_events=2,
            total_events_considered=573,
        )
    )
    # TestClient sem context manager: não dispara o lifespan/refresh_loop,
    # então o snapshot publicado acima não é sobrescrito
    return TestClient(app)


# --- /get-pools --------------------------------------------------------------


def test_get_pools_returns_best_pool_without_filters(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/get-pools")
    assert response.status_code == 200
    body = response.json()
    assert body["pool_id"] in SAMPLE_STATS
    assert "score" in body
    assert "stats" in body
    assert "alternatives" in body


def test_get_pools_filters_by_instance_family(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/get-pools?instance_family=r6")
    assert response.status_code == 200
    assert response.json()["pool_id"].startswith("pool-r6")


def test_get_pools_filters_by_instance_type(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/get-pools?instance_type=c6.xlarge")
    assert response.status_code == 200
    assert response.json()["pool_id"] == "pool-c6.xlarge-us-east-1b"


def test_get_pools_filters_by_az(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/get-pools?az=us-east-1a")
    assert response.status_code == 200
    assert response.json()["pool_id"].endswith("us-east-1a")


def test_get_pools_impossible_filter_returns_404(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/get-pools?instance_type=t3.nano")
    assert response.status_code == 404
    assert "detail" in response.json()


def test_get_pools_argmax_strategy_is_deterministic(client_with_sample_snapshot):
    responses = [client_with_sample_snapshot.get("/get-pools?strategy=argmax").json()["pool_id"] for _ in range(10)]
    assert len(set(responses)) == 1
    assert responses[0] == "pool-r6.xlarge-us-east-1a"  # maior nota do SAMPLE_STATS


def test_get_pools_invalid_strategy_returns_422(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/get-pools?strategy=nao-existe")
    assert response.status_code == 422


def test_get_pools_alias_returns_same_shape_as_canonical(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/get-pool?strategy=argmax")
    assert response.status_code == 200
    assert response.json()["pool_id"] == "pool-r6.xlarge-us-east-1a"


def test_get_pools_stats_expose_ignored_events(client_with_sample_snapshot):
    """O pool com falhas de job (patológico) deve mostrar isso em stats,
    provando que a decisão é inspecionável sem ler código."""
    response = client_with_sample_snapshot.get("/get-pools?instance_type=c6.xlarge")
    assert response.json()["stats"]["ignored_events"] == 80


def test_get_pools_respects_limit_parameter(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/get-pools?limit=2")
    assert len(response.json()["alternatives"]) <= 2


def test_get_pools_empty_snapshot_returns_503():
    snapshot_store.publish(EMPTY_SNAPSHOT)
    client = TestClient(app)

    response = client.get("/get-pools")

    assert response.status_code == 503


# --- /health -------------------------------------------------------------


def test_health_reports_snapshot_state(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/health")
    body = response.json()

    assert body["status"] == "ok"
    assert body["pools_tracked"] == len(SAMPLE_STATS)
    assert body["total_events_considered"] == 573
    assert body["malformed_events"] == 2
    assert body["event_source"] == "local"


def test_health_reports_live_scoring_parameters(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/health")
    params = response.json()["parameters"]

    assert "lookback_hours" in params
    assert "courtesy_points" in params
    assert "top_k" in params


def test_health_works_even_with_empty_snapshot():
    snapshot_store.publish(EMPTY_SNAPSHOT)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["pools_tracked"] == 0


# --- /metrics --------------------------------------------------------------


def _parse_metrics(client):
    """Lê /metrics e devolve as famílias já parseadas pelo parser oficial."""
    response = client.get("/metrics")
    families = list(text_string_to_metric_families(response.text))
    return response, families


def _requests_total_by_status(families, status):
    for family in families:
        if family.name == "pool_selector_requests":
            for sample in family.samples:
                if sample.labels.get("status") == status:
                    return sample.value
    return 0.0


def test_metrics_returns_200_with_prometheus_content_type(client_with_sample_snapshot):
    response = client_with_sample_snapshot.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"


def test_metrics_contains_the_five_required_metrics(client_with_sample_snapshot):
    _, families = _parse_metrics(client_with_sample_snapshot)
    names = {family.name for family in families}

    assert "pool_selector_snapshot_age_seconds" in names
    assert "pool_selector_pools_tracked" in names
    assert "pool_selector_events_total" in names
    assert "pool_selector_malformed_events_total" in names
    # o Counter aparece sem o sufixo "_total" no nome de família (ver
    # tests/test_metrics.py para a explicação dessa convenção do parser)
    assert "pool_selector_requests" in names


def test_metrics_gauges_reflect_published_snapshot(client_with_sample_snapshot):
    _, families = _parse_metrics(client_with_sample_snapshot)
    values = {family.name: family.samples[0].value for family in families if family.name != "pool_selector_requests"}

    assert values["pool_selector_pools_tracked"] == len(SAMPLE_STATS)
    assert values["pool_selector_events_total"] == 573
    assert values["pool_selector_malformed_events_total"] == 2


def test_metrics_counts_two_consecutive_404s_by_diff(client_with_sample_snapshot):
    _, before_families = _parse_metrics(client_with_sample_snapshot)
    before = _requests_total_by_status(before_families, "404")

    client_with_sample_snapshot.get("/get-pools?instance_type=t3.nano")
    client_with_sample_snapshot.get("/get-pools?instance_type=t3.nano")

    _, after_families = _parse_metrics(client_with_sample_snapshot)
    after = _requests_total_by_status(after_families, "404")

    assert after - before == 2


def test_metrics_counts_200_and_503_by_diff(client_with_sample_snapshot):
    _, before_families = _parse_metrics(client_with_sample_snapshot)
    before_200 = _requests_total_by_status(before_families, "200")
    before_503 = _requests_total_by_status(before_families, "503")

    client_with_sample_snapshot.get("/get-pools")

    original_snapshot = snapshot_store.current
    snapshot_store.publish(EMPTY_SNAPSHOT)
    client_with_sample_snapshot.get("/get-pools")
    snapshot_store.publish(original_snapshot)

    _, after_families = _parse_metrics(client_with_sample_snapshot)
    after_200 = _requests_total_by_status(after_families, "200")
    after_503 = _requests_total_by_status(after_families, "503")

    assert after_200 - before_200 == 1
    assert after_503 - before_503 == 1
