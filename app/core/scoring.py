"""
Algoritmo de scoring: sistema de pontos que ranqueia pools de instâncias
spot pela probabilidade de um job executar sem perder a instância.

O racional completo da escolha está em docs/adr/0003-algoritmo-scoring.md; 
resumo: como o passo final sorteia entre os melhores candidatos, ganhar 
resolução decimal na nota não muda o resultado, e um cálculo auditável de 
cabeça é mais valioso operacionalmente do que alguns pontos percentuais 
de precisão.

Funções puras, sem I/O: recebem eventos e o instante de referência, devolvem
dados. Isso é o que torna o algoritmo testável em isolamento (TDD) e reusável
tanto para o loop de ingestão (Etapa 3) quanto para testes de regressão.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from app.core.config import settings
from app.domain.events import JobEvent, Reason, Status


@dataclass(frozen=True)
class PoolStats:
    """
    Estatísticas acumuladas de um pool, já com os pontos ponderados por idade.
    """

    pool_id: str
    good_points: float  # soma dos pesos dos eventos SUCCESS
    bad_points: float  # soma dos pesos dos eventos FAILED/SPOT_INSTANCE_TERMINATION
    ignored_events: int  # contagem de TIMED_OUT/SPARK_EXECUTION_ERROR (diagnóstico)
    total_events: int  # contagem bruta de eventos considerados (good + bad + ignored)

    @property
    def score(self) -> float:
        """
        Nota entre 0 e 1: fração de pontos bons, com pontos de cortesia
        de cada lado para não deixar um pool com poucos eventos vencer por
        sorte. Pool sem nenhum evento dá nota = 0.5 automaticamente.
        """
        courtesy = settings.courtesy_points
        return (self.good_points + courtesy) / (self.good_points + self.bad_points + 2 * courtesy)


def weight_by_age(age_hours: float) -> float:
    """
    Peso de um evento conforme sua idade. Eventos recentes pesam mais —
    é como a API reage a uma AZ que piorou "só agora", ao invés de diluir o
    sinal na média histórica do dia inteiro. Eventos mais velhos que a
    janela de lookback são descartados (peso 0).
    """
    if age_hours < 0:
        # evento no "futuro" (relógio do produtor adiantado, por exemplo) —
        # trata como o mais recente possível ao invés de rejeitar
        age_hours = 0.0
    if age_hours < settings.window_recent_h:
        return float(settings.weight_recent)
    if age_hours < settings.window_mid_h:
        return float(settings.weight_mid)
    if age_hours < settings.lookback_hours:
        return float(settings.weight_old)
    return 0.0


def classify_event(event: JobEvent) -> str:
    """
    Classifica um evento em 'good', 'bad' ou 'ignored'.

    Só SPOT_INSTANCE_TERMINATION é sinal de disponibilidade da AZ. As outras
    duas razões de falha (TIMED_OUT, SPARK_EXECUTION_ERROR) dizem que o job
    é ruim, não o pool — contá-las deixaria um job mal escrito envenenar o
    ranking de um pool saudável.
    """
    if event.status == Status.SUCCESS:
        return "good"
    if event.reason == Reason.SPOT_INSTANCE_TERMINATION:
        return "bad"
    return "ignored"


def compute_stats(events: list[JobEvent], now: datetime) -> dict[str, PoolStats]:
    """
    Agrega uma lista de eventos em estatísticas por pool.

    Função pura central do algoritmo: dado um conjunto de eventos e um
    instante de referência, devolve as estatísticas ponderadas de cada pool
    observado. Quem chama decide de onde vieram os eventos
    (disco, S3, um teste) e quando é "agora".
    """
    accumulated: dict[str, list[tuple[str, float]]] = defaultdict(list)

    for event in events:
        age_hours = (now - event.finished_at).total_seconds() / 3600
        weight = weight_by_age(age_hours)
        if weight == 0.0:
            continue  # fora da janela de lookback, não conta em nada

        cls = classify_event(event)
        accumulated[event.pool_id].append((cls, weight))

    stats: dict[str, PoolStats] = {}
    for pool_id, entries in accumulated.items():
        good_points = sum(weight for cls, weight in entries if cls == "good")
        bad_points = sum(weight for cls, weight in entries if cls == "bad")
        n_ignored = sum(1 for cls, _ in entries if cls == "ignored")
        stats[pool_id] = PoolStats(
            pool_id=pool_id,
            good_points=good_points,
            bad_points=bad_points,
            ignored_events=n_ignored,
            total_events=len(entries),
        )
    return stats


def rank(stats: dict[str, PoolStats]) -> list[PoolStats]:
    """
    Ordena os pools da maior para a menor nota. Empates são desfeitos
    por pool_id para tornar a ordem determinística em testes.
    """
    return sorted(stats.values(), key=lambda s: (-s.score, s.pool_id))


def choose_pool(
    stats: dict[str, PoolStats],
    strategy: str = "sample",
    rng: random.Random | None = None,
) -> tuple[PoolStats, list[PoolStats]]:
    """
    Escolhe um pool dentre os melhores candidatos.

    strategy="sample" (padrão): sorteia entre os TOP_K melhores, com
    chance proporcional à nota. Evita que uma rajada de jobs mande todos
    para o mesmo pool e estoure a capacidade da AZ que os atraiu — o
    próprio ato de recomendar mudaria os dados que a recomendação usa.

    strategy="argmax": sempre devolve o melhor pool, determinístico.
    Útil para testes e para depuração ("qual pool venceria sem o sorteio?").

    Devolve (pool_escolhido, lista_de_alternativas_consideradas).
    """
    if not stats:
        raise ValueError("nenhum pool disponível para escolher")

    candidates = rank(stats)[: settings.top_k]

    if strategy == "argmax":
        return candidates[0], candidates

    rng = rng or random.Random()
    weights = [c.score for c in candidates]
    chosen = rng.choices(candidates, weights=weights, k=1)[0]
    return chosen, candidates
