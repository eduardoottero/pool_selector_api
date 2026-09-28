"""
Snapshot imutável do ranking de pools.

O snapshot é o que separa o cálculo
(que pode ser custoso, ler todos os eventos da janela de lookback)
do atendimento de uma requisição (que precisa ser O(1) mesmo sob rajada).
O loop de ingestão (refresher.py) recalcula o snapshot periodicamente e o publica aqui;
o endpoint da API só lê o snapshot publicado, nunca recalcula nada na hora da requisição.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.scoring import PoolStats


@dataclass(frozen=True)
class RankingSnapshot:
    """
    Estado imutável do ranking em um dado instante.

    Frozen (imutável) por design: depois de criado, um snapshot nunca muda.
    Isso é o que garante que múltiplas requisições lendo o mesmo snapshot
    concorrentemente nunca vejam um estado inconsistente — não há nada para
    mudar sob elas.
    """

    stats: dict[str, PoolStats]
    built_at: datetime
    malformed_events: int
    total_events_considered: int

    @property
    def age_seconds(self) -> float:
        """
        Há quanto tempo este snapshot foi construído — usado no /health para detectar um refresher travado.
        """
        return (datetime.now(UTC) - self.built_at).total_seconds()


EMPTY_SNAPSHOT = RankingSnapshot(stats={}, built_at=datetime.now(UTC), malformed_events=0, total_events_considered=0)


class SnapshotStore:
    """
    Guarda a referência ao snapshot atual e implementa a troca.

    """

    def __init__(self) -> None:
        self._current: RankingSnapshot = EMPTY_SNAPSHOT

    @property
    def current(self) -> RankingSnapshot:
        return self._current

    def publish(self, snapshot: RankingSnapshot) -> None:
        """
        Publica um novo snapshot.
        """
        self._current = snapshot


# instância única usada pela aplicação (refresher publica, rotas leem)
snapshot_store = SnapshotStore()
