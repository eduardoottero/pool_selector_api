"""
Testes do algoritmo de scoring — o núcleo do projeto.

Cada teste aqui corresponde a um dos comportamentos que justificam as
decisões de design do algoritmo (ver docs/algorithm.md e o ADR de scoring):
amostra pequena não deve vencer por sorte, falha de job não deve contar
contra o pool, eventos recentes pesam mais que antigos, cold start é
tratado sem favorecer nem excluir, e o sorteio evita determinismo total.
"""

import random
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.core.scoring import (
    PoolStats,
    choose_pool,
    classify_event,
    compute_stats,
    rank,
    weight_by_age,
)
from app.domain.events import JobEvent, Reason, Status

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _event(pool_id, status, reason=None, age_hours=0.0, job_id="test-job"):
    return JobEvent(
        finished_at=NOW - timedelta(hours=age_hours),
        job_id=job_id,
        pool_id=pool_id,
        status=status,
        reason=reason,
    )


def _stats(pool_id, good, bad, ignored=0):
    """Atalho para construir PoolStats nos testes sem repetir todos os campos."""
    return PoolStats(
        pool_id=pool_id,
        good_points=good,
        bad_points=bad,
        ignored_events=ignored,
        total_events=good + bad + ignored,
    )


# --- weight_by_age -----------------------------------------------------------


def test_recent_event_has_maximum_weight():
    assert weight_by_age(0.5) == settings.weight_recent


def test_mid_age_event_weighs_less_than_recent():
    weight = weight_by_age(3.0)  # entre window_recent_h (1) e window_mid_h (6)
    assert weight == settings.weight_mid
    assert weight < settings.weight_recent


def test_old_event_has_minimum_weight():
    # ponto médio entre window_mid_h e lookback_hours, garantido cair na faixa "antiga"
    old_age = (settings.window_mid_h + settings.lookback_hours) / 2
    weight = weight_by_age(old_age)
    assert weight == settings.weight_old
    assert weight < settings.weight_mid


def test_event_outside_lookback_window_has_zero_weight():
    assert weight_by_age(settings.lookback_hours + 1) == 0.0


def test_recent_event_weighs_more_than_old_event():
    """Verificação direta do critério do plano: evento na última hora vale
    3x um evento na faixa "antiga" (pesos default 3 e 1)."""
    old_age = (settings.window_mid_h + settings.lookback_hours) / 2
    assert weight_by_age(0.5) == 3 * weight_by_age(old_age)


# --- classify_event ------------------------------------------------------


def test_success_is_classified_as_good():
    e = _event("pool-r6.xlarge-us-east-1a", Status.SUCCESS)
    assert classify_event(e) == "good"


def test_spot_termination_is_classified_as_bad():
    e = _event("pool-r6.xlarge-us-east-1a", Status.FAILED, reason=Reason.SPOT_INSTANCE_TERMINATION)
    assert classify_event(e) == "bad"


@pytest.mark.parametrize("reason", [Reason.TIMED_OUT, Reason.SPARK_EXECUTION_ERROR])
def test_job_failure_is_ignored_does_not_count_against_pool(reason):
    e = _event("pool-r6.xlarge-us-east-1a", Status.FAILED, reason=reason)
    assert classify_event(e) == "ignored"


# --- compute_stats + score --------------------------------------------------


def test_pool_with_many_job_failures_keeps_high_score():
    """O teste mais importante do projeto: um pool que recebe 80 falhas de
    job (TIMED_OUT/SPARK_EXECUTION_ERROR) ao lado de execuções saudáveis não
    pode ter a nota derrubada por isso — são falhas do job, não do pool."""
    events = [_event("pool-c6.xlarge-us-east-1b", Status.SUCCESS) for _ in range(20)]
    events += [
        _event("pool-c6.xlarge-us-east-1b", Status.FAILED, reason=Reason.TIMED_OUT)
        for _ in range(80)
    ]

    stats = compute_stats(events, now=NOW)
    pool = stats["pool-c6.xlarge-us-east-1b"]

    assert pool.ignored_events == 80
    assert pool.bad_points == 0  # nenhuma falha de job vira ponto ruim
    assert pool.score > 0.9  # nota alta, como se as 80 falhas não existissem


def test_lucky_newcomer_loses_to_workhorse_with_large_sample():
    """O teste central do sistema de pontos: um pool com poucos eventos e
    100% de sucesso não deve vencer um pool com muitos eventos e boa
    (mas não perfeita) taxa de sucesso."""
    newcomer = [
        _event("pool-r6.2xlarge-us-east-1d", Status.SUCCESS, age_hours=0.2) for _ in range(2)
    ]

    workhorse = [
        _event("pool-r6.xlarge-us-east-1a", Status.SUCCESS, age_hours=1) for _ in range(485)
    ]
    workhorse += [
        _event(
            "pool-r6.xlarge-us-east-1a",
            Status.FAILED,
            reason=Reason.SPOT_INSTANCE_TERMINATION,
            age_hours=1,
        )
        for _ in range(15)
    ]

    stats = compute_stats(newcomer + workhorse, now=NOW)

    newcomer_score = stats["pool-r6.2xlarge-us-east-1d"].score
    workhorse_score = stats["pool-r6.xlarge-us-east-1a"].score

    assert (
        newcomer_score < workhorse_score
    ), f"newcomer ({newcomer_score:.3f}) não deveria vencer o workhorse ({workhorse_score:.3f})"


def test_pool_with_no_events_has_neutral_cold_start_score():
    """Um pool sem eventos não aparece em `stats` (compute_stats só vê o
    que existe no histórico) — mas se PoolStats for construído com zero
    pontos dos dois lados, a nota deve ser exatamente 0.5: nem favorecido,
    nem excluído."""
    new_pool = _stats("pool-i3.xlarge-us-east-1a", good=0, bad=0)
    assert new_pool.score == pytest.approx(0.5)


def test_event_outside_lookback_window_does_not_appear_in_stats():
    events = [_event("pool-r6.xlarge-us-east-1a", Status.SUCCESS, age_hours=100)]
    stats = compute_stats(events, now=NOW)
    assert "pool-r6.xlarge-us-east-1a" not in stats


# --- rank ----------------------------------------------------------------


def test_rank_orders_from_highest_to_lowest_score():
    stats = {
        "pool-low": _stats("pool-low", good=5, bad=10),
        "pool-high": _stats("pool-high", good=50, bad=1),
        "pool-mid": _stats("pool-mid", good=20, bad=5),
    }
    ranking = rank(stats)
    assert [p.pool_id for p in ranking] == ["pool-high", "pool-mid", "pool-low"]


# --- choose_pool (anti-manada) ---------------------------------------------


def test_choose_pool_argmax_strategy_is_deterministic():
    stats = {
        "pool-a": _stats("pool-a", good=90, bad=1),
        "pool-b": _stats("pool-b", good=10, bad=10),
    }
    chosen, alternatives = choose_pool(stats, strategy="argmax")
    assert chosen.pool_id == "pool-a"
    assert alternatives[0].pool_id == "pool-a"


def test_choose_pool_sample_strategy_with_seed_is_reproducible():
    stats = {
        "pool-a": _stats("pool-a", good=60, bad=5),
        "pool-b": _stats("pool-b", good=55, bad=5),
        "pool-c": _stats("pool-c", good=50, bad=5),
    }
    chosen1, _ = choose_pool(stats, strategy="sample", rng=random.Random(7))
    chosen2, _ = choose_pool(stats, strategy="sample", rng=random.Random(7))
    assert chosen1.pool_id == chosen2.pool_id


def test_choose_pool_sample_distributes_across_candidates_over_many_calls():
    """Prova o comportamento anti-manada: com pools de nota parecida, o
    sorteio não escolhe sempre o mesmo — a carga se espalha."""
    stats = {
        "pool-a": _stats("pool-a", good=55, bad=5),
        "pool-b": _stats("pool-b", good=53, bad=5),
        "pool-c": _stats("pool-c", good=51, bad=5),
    }
    rng = random.Random(123)
    chosen_ids = {choose_pool(stats, strategy="sample", rng=rng)[0].pool_id for _ in range(50)}

    assert len(chosen_ids) > 1, "esperava que mais de um pool fosse escolhido em 50 sorteios"


def test_choose_pool_only_considers_up_to_top_k_candidates():
    """Um pool com nota muito baixa, fora do top_k, nunca deve ser escolhido
    mesmo que a estratégia seja sample."""
    stats = {f"pool-{i}": _stats(f"pool-{i}", good=100 - i, bad=1) for i in range(10)}
    rng = random.Random(1)
    chosen_ids = {choose_pool(stats, strategy="sample", rng=rng)[0].pool_id for _ in range(100)}

    worst_pools = {f"pool-{i}" for i in range(settings.top_k, 10)}
    assert chosen_ids.isdisjoint(worst_pools)


def test_choose_pool_raises_error_without_candidates():
    with pytest.raises(ValueError):
        choose_pool({})
