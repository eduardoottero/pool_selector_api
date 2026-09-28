"""
Testes de app/core/metrics.py isolado — sem subir a app FastAPI.

Como os coletores (Counter/Gauge) são objetos de módulo, compartilhados
por todos os testes deste processo, as asserções sobre o Counter de
requisições comparam a variação (antes/depois), nunca o valor absoluto —
mesmo cuidado que tests/test_routes.py toma com snapshot_store.
"""

from datetime import UTC, datetime

from prometheus_client.parser import text_string_to_metric_families

from app.core.metrics import REQUESTS_TOTAL, record_request, render_metrics
from app.core.scoring import PoolStats
from app.core.snapshot import RankingSnapshot


def _requests_total(status: str) -> float:
    return REQUESTS_TOTAL.labels(status=status)._value.get()  # type: ignore[attr-defined]


# --- record_request ---------------------------------------------------------


def test_record_request_increments_counter_for_given_status():
    before = _requests_total("200")
    record_request(200)
    after = _requests_total("200")

    assert after == before + 1


def test_record_request_does_not_affect_other_status_labels():
    before_404 = _requests_total("404")
    record_request(200)
    after_404 = _requests_total("404")

    assert after_404 == before_404


def test_record_request_accepts_each_tracked_status():
    for status in (200, 404, 503):
        before = _requests_total(str(status))
        record_request(status)
        after = _requests_total(str(status))

        assert after == before + 1


# --- render_metrics ----------------------------------------------------------


def _sample_snapshot() -> RankingSnapshot:
    stats = {
        "pool-r6.xlarge-us-east-1a": PoolStats(
            pool_id="pool-r6.xlarge-us-east-1a",
            good_points=238.0,
            bad_points=5.0,
            ignored_events=0,
            total_events=172,
        ),
        "pool-c6.xlarge-us-east-1b": PoolStats(
            pool_id="pool-c6.xlarge-us-east-1b",
            good_points=100.0,
            bad_points=5.0,
            ignored_events=80,
            total_events=185,
        ),
    }
    return RankingSnapshot(
        stats=stats,
        built_at=datetime.now(UTC),
        malformed_events=3,
        total_events_considered=357,
    )


def _metric_value(families, name, labels=None):
    for family in families:
        if family.name == name:
            for sample in family.samples:
                if labels is None or sample.labels == labels:
                    return sample.value
    return None


def test_render_metrics_reflects_snapshot_fields_in_gauges():
    snapshot = _sample_snapshot()
    body = render_metrics(snapshot)

    families = list(text_string_to_metric_families(body.decode("utf-8")))

    assert _metric_value(families, "pool_selector_pools_tracked") == len(snapshot.stats)
    assert _metric_value(families, "pool_selector_events_total") == snapshot.total_events_considered
    assert _metric_value(families, "pool_selector_malformed_events_total") == snapshot.malformed_events
    age = _metric_value(families, "pool_selector_snapshot_age_seconds")
    assert age is not None
    assert age >= 0.0


def test_render_metrics_output_is_nonempty_bytes():
    body = render_metrics(_sample_snapshot())

    assert isinstance(body, bytes)
    assert len(body) > 0


def test_render_metrics_output_parses_with_official_parser_and_declares_correct_types():
    body = render_metrics(_sample_snapshot())

    families = {family.name: family for family in text_string_to_metric_families(body.decode("utf-8"))}

    expected_gauges = {
        "pool_selector_snapshot_age_seconds",
        "pool_selector_pools_tracked",
        "pool_selector_events_total",
        "pool_selector_malformed_events_total",
    }
    for name in expected_gauges:
        assert name in families
        assert families[name].type == "gauge"

    # o parser normaliza o nome de família de um Counter removendo o
    # sufixo "_total" (convenção do formato Prometheus) — as amostras
    # individuais continuam expondo o nome completo com o sufixo.
    assert "pool_selector_requests" in families
    requests_family = families["pool_selector_requests"]
    assert requests_family.type == "counter"
    assert all(sample.name == "pool_selector_requests_total" for sample in requests_family.samples)
