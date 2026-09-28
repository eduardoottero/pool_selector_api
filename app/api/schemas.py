"""
Schemas de request/response do endpoint /get-pools.

Utilizando pydantic aqui, ao invés de dicts soltos, para permitir a validação automática dos parâmetros.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PoolStatsResponse(BaseModel):
    """Estatísticas do pool escolhido"""

    good_points: float
    bad_points: float
    ignored_events: int = Field(description="eventos TIMED_OUT/SPARK_EXECUTION_ERROR excluídos")
    total_events: int


class PoolCandidate(BaseModel):
    """Um pool candidato, com sua nota: usado tanto para o escolhido
    quanto para a lista de pools alternativas."""

    pool_id: str
    score: float


class GetPoolsResponse(BaseModel):
    pool_id: str
    score: float
    stats: PoolStatsResponse
    alternatives: list[PoolCandidate]
    strategy: str
    snapshot_age_seconds: float


class HealthResponse(BaseModel):
    status: str
    snapshot_age_seconds: float
    pools_tracked: int
    total_events_considered: int
    malformed_events: int
    event_source: str
    parameters: dict[str, float | int]
