"""Modelo do evento de finalização de job Spark e o parsing do pool_id.

Este módulo é usado tanto pelo gerador de dados sintéticos (Etapa 1) quanto
pela ingestão real (Etapa 3) — a mesma estrutura de dados representa um
evento lido do S3 e um evento escrito pelo gerador.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, field_validator

# pool_id no formato "pool-<instance-type>-<az>", ex.: pool-r6.xlarge-us-east-1a
_POOL_ID_RE = re.compile(r"^pool-(?P<instance_type>[a-z0-9]+\.[a-z0-9]+)-(?P<az>[a-z0-9-]+)$")


@dataclass(frozen=True)
class ParsedPoolId:
    instance_type: str
    instance_family: str
    az: str


def parse_pool_id(pool_id: str) -> ParsedPoolId:
    """Extrai instance_type/instance_family/az de um pool_id, sem exigir um
    JobEvent completo — usado pelas rotas da API (Etapa 4) para filtrar por
    esses campos sem duplicar o regex nem montar um evento fake."""
    match = _POOL_ID_RE.match(pool_id)
    if not match:
        raise ValueError(f"pool_id fora do formato pool-<instance-type>-<az>: {pool_id!r}")
    instance_type = match["instance_type"]
    return ParsedPoolId(
        instance_type=instance_type,
        instance_family=instance_type.split(".")[0],
        az=match["az"],
    )


class Status(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Reason(StrEnum):
    """Motivo da falha. Só SPOT_INSTANCE_TERMINATION é sinal de disponibilidade
    da AZ — os outros dois dizem que o *job* é ruim, não o *pool*."""

    SPOT_INSTANCE_TERMINATION = "SPOT_INSTANCE_TERMINATION"
    TIMED_OUT = "TIMED_OUT"
    SPARK_EXECUTION_ERROR = "SPARK_EXECUTION_ERROR"


class JobEvent(BaseModel):
    """Um evento de finalização de job Spark, como chega no S3 (uma linha JSONL)."""

    finished_at: datetime
    job_id: str
    pool_id: str
    status: Status
    reason: Reason | None = None

    @field_validator("pool_id")
    @classmethod
    def _validate_pool_id_format(cls, v: str) -> str:
        parse_pool_id(v)  # levanta ValueError se o formato for inválido
        return v

    @property
    def instance_type(self) -> str:
        """Ex.: 'r6.xlarge' extraído de 'pool-r6.xlarge-us-east-1a'."""
        return parse_pool_id(self.pool_id).instance_type

    @property
    def instance_family(self) -> str:
        """Ex.: 'r6' extraído de 'r6.xlarge' — a parte antes do ponto."""
        return parse_pool_id(self.pool_id).instance_family

    @property
    def az(self) -> str:
        """Ex.: 'us-east-1a' extraído de 'pool-r6.xlarge-us-east-1a'."""
        return parse_pool_id(self.pool_id).az
