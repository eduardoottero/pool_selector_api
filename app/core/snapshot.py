"""Snapshot imutável do ranking de pools, e a troca atômica de ponteiro.

O snapshot é o que separa o cálculo (que pode ser custoso, ler todos os
eventos da janela de lookback) do atendimento de uma requisição (que precisa
ser O(1) mesmo sob rajada). O loop de ingestão (refresher.py) recalcula o
snapshot periodicamente e o publica aqui; o endpoint da API só lê o snapshot
publicado, nunca recalcula nada na hora da requisição.

"Troca atômica de ponteiro": o Python tem um GIL (Global Interpreter Lock)
que serializa a execução de bytecode entre threads — uma atribuição simples
como `_current = novo_snapshot` é uma única operação de bytecode, então não
existe um instante em que uma requisição concorrente veria um estado
parcialmente atualizado. Um leitor que já pegou uma referência ao snapshot
antigo continua usando-a até terminar, mesmo que o refresher já tenha
publicado um novo — não é preciso lock nenhum para isso funcionar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.scoring import PoolStats


@dataclass(frozen=True)
class RankingSnapshot:
    """Estado imutável do ranking em um dado instante.

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
        """Há quanto tempo este snapshot foi construído — usado no /health
        para detectar um refresher travado (ver docstring do módulo)."""
        return (datetime.now(UTC) - self.built_at).total_seconds()


EMPTY_SNAPSHOT = RankingSnapshot(
    stats={}, built_at=datetime.now(UTC), malformed_events=0, total_events_considered=0
)


class SnapshotStore:
    """Guarda a referência ao snapshot atual e implementa a troca atômica.

    Uma classe simples em vez de uma variável de módulo solta: facilita
    injeção em testes (cada teste cria seu próprio `SnapshotStore`, sem
    interferir uns nos outros) e deixa explícito, pelo nome, o que está
    sendo compartilhado entre o refresher e as rotas da API.
    """

    def __init__(self) -> None:
        self._current: RankingSnapshot = EMPTY_SNAPSHOT

    @property
    def current(self) -> RankingSnapshot:
        return self._current

    def publish(self, snapshot: RankingSnapshot) -> None:
        """Publica um novo snapshot. Rebind simples de atributo — atômico
        sob o GIL, sem necessidade de lock (ver docstring do módulo)."""
        self._current = snapshot


# instância única usada pela aplicação (refresher publica, rotas leem)
snapshot_store = SnapshotStore()
