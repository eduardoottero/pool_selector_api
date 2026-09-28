"""
Métricas de observabilidade no formato de exposição do Prometheus.

"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

from app.core.snapshot import RankingSnapshot

registry = CollectorRegistry()

SNAPSHOT_AGE_SECONDS = Gauge(
    "pool_selector_snapshot_age_seconds",
    "Idade, em segundos, do snapshot de ranking atualmente publicado.",
    registry=registry,
)
POOLS_TRACKED = Gauge(
    "pool_selector_pools_tracked",
    "Quantidade de pools distintos presentes no snapshot atual.",
    registry=registry,
)
EVENTS_TOTAL = Gauge(
    "pool_selector_events_total",
    "Total de eventos considerados na construção do snapshot atual"
    " (dentro da janela de lookback).",
    registry=registry,
)
MALFORMED_EVENTS_TOTAL = Gauge(
    "pool_selector_malformed_events_total",
    "Total de linhas malformadas descartadas na construção do snapshot atual.",
    registry=registry,
)
REQUESTS_TOTAL = Counter(
    "pool_selector_requests_total",
    "Total de requisições a /get-pools (e seu alias /get-pool), por código de resposta.",
    ["status"],
    registry=registry,
)


def record_request(status: int) -> None:
    """
    Incrementa o contador de requisições a /get-pools para o código
    de resposta informado. Chamada pelas rotas.
    """
    REQUESTS_TOTAL.labels(status=str(status)).inc()


def render_metrics(snapshot: RankingSnapshot) -> bytes:
    """
    Atualiza os gauges derivados do snapshot atual e serializa todas
    as métricas registradas no formato de exposição do Prometheus.
    """
    SNAPSHOT_AGE_SECONDS.set(snapshot.age_seconds)
    POOLS_TRACKED.set(len(snapshot.stats))
    EVENTS_TOTAL.set(snapshot.total_events_considered)
    MALFORMED_EVENTS_TOTAL.set(snapshot.malformed_events)
    return generate_latest(registry)
