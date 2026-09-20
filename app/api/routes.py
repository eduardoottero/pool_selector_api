"""Rotas da API: /get-pools (+ alias /get-pool) e /health.

O enunciado do desafio usa /get-pool num trecho e /get-pools (com a porta
5050) noutro — servimos os dois apontando para o mesmo handler, e
documentamos a ambiguidade no ADR correspondente (Etapa 7), em vez de
escolher um dos dois por adivinhação.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import (
    GetPoolsResponse,
    HealthResponse,
    PoolCandidate,
    PoolStatsResponse,
)
from app.core.config import settings
from app.core.scoring import PoolStats, choose_pool
from app.core.snapshot import snapshot_store
from app.domain.events import parse_pool_id

router = APIRouter()


def _matches_filters(
    pool: PoolStats,
    instance_family: list[str] | None,
    instance_type: list[str] | None,
    az: list[str] | None,
) -> bool:
    """Extrai instance_type/instance_family/az do pool_id para aplicar os
    filtros do requisito 2, sem precisar guardar esses campos separadamente
    em PoolStats (que é deliberadamente enxuto — ver Etapa 2)."""
    parsed = parse_pool_id(pool.pool_id)

    if instance_type and parsed.instance_type not in instance_type:
        return False
    if instance_family and parsed.instance_family not in instance_family:
        return False
    if az and parsed.az not in az:
        return False
    return True


@router.get("/get-pools", response_model=GetPoolsResponse)
@router.get("/get-pool", response_model=GetPoolsResponse)
def get_pools(
    instance_family: list[str] | None = Query(
        default=None,
        description="Restringe a famílias de instância (ex.: r6 para memória, c6 para CPU)."
        " Repita o parâmetro para várias famílias.",
    ),
    instance_type: list[str] | None = Query(
        default=None,
        description="Restringe a tipos exatos de instância (ex.: r6.xlarge)."
        " Repita o parâmetro para vários tipos.",
    ),
    az: list[str] | None = Query(
        default=None, description="Restringe a AZs específicas (ex.: us-east-1a)."
    ),
    limit: int = Query(default=3, ge=1, le=10, description="Quantas alternativas retornar."),
    strategy: str = Query(
        default="sample",
        pattern="^(sample|argmax)$",
        description="'sample' (padrão) sorteia entre os melhores pools, evitando que uma"
        " rajada de jobs sobrecarregue sempre a mesma AZ. 'argmax' é determinístico,"
        " útil para depuração e testes.",
    ),
) -> GetPoolsResponse:
    snapshot = snapshot_store.current

    if not snapshot.stats:
        raise HTTPException(
            status_code=503,
            detail="nenhum dado de pool disponível ainda —"
            " o snapshot inicial está sendo construído",
        )

    filtered = {
        pool_id: stats
        for pool_id, stats in snapshot.stats.items()
        if _matches_filters(stats, instance_family, instance_type, az)
    }

    if not filtered:
        raise HTTPException(
            status_code=404,
            detail="nenhum pool encontrado para os filtros informados"
            f" (instance_family={instance_family}, instance_type={instance_type}, az={az})",
        )

    chosen, candidates = choose_pool(filtered, strategy=strategy)

    return GetPoolsResponse(
        pool_id=chosen.pool_id,
        score=chosen.score,
        stats=PoolStatsResponse(
            good_points=chosen.good_points,
            bad_points=chosen.bad_points,
            ignored_events=chosen.ignored_events,
            total_events=chosen.total_events,
        ),
        alternatives=[PoolCandidate(pool_id=c.pool_id, score=c.score) for c in candidates[:limit]],
        strategy=strategy,
        snapshot_age_seconds=round(snapshot.age_seconds, 3),
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    snapshot = snapshot_store.current
    return HealthResponse(
        status="ok",
        snapshot_age_seconds=round(snapshot.age_seconds, 3),
        pools_tracked=len(snapshot.stats),
        total_events_considered=snapshot.total_events_considered,
        malformed_events=snapshot.malformed_events,
        event_source=settings.event_source,
        parameters={
            "lookback_hours": settings.lookback_hours,
            "weight_recent": settings.weight_recent,
            "weight_mid": settings.weight_mid,
            "weight_old": settings.weight_old,
            "window_recent_h": settings.window_recent_h,
            "window_mid_h": settings.window_mid_h,
            "courtesy_points": settings.courtesy_points,
            "top_k": settings.top_k,
            "refresh_interval_seconds": settings.refresh_interval_seconds,
        },
    )
