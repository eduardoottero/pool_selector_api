"""Gerador de dados sintéticos de eventos de finalização de job Spark.

Não existem dados reais para este desafio — este gerador *é* a demonstração.
Ele planta 5 cenários deliberados que fazem o algoritmo de scoring (Etapa 2)
produzir um resultado visivelmente não-trivial, além de "ruído de fundo"
realista (chegada de jobs variando ao longo do dia, várias famílias de
instância e AZs).

Determinístico via --seed: a mesma semente sempre gera o mesmo dataset,
o que torna a demonstração e os testes reprodutíveis.

Saída: um arquivo JSONL por hora, em <out>/<data>/<hora>.jsonl — imita o
layout realista de um bucket S3 particionado por tempo, e serve para a
Etapa 3 exercitar leitura incremental de múltiplos objetos.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.domain.events import Reason, Status

# --- vocabulário de instâncias e AZs usado no ruído de fundo ---

MEMORY_FAMILIES = ["r6.xlarge", "r6.2xlarge", "r5.xlarge"]
CPU_FAMILIES = ["c6.xlarge", "c6.2xlarge", "c5.xlarge"]
STORAGE_FAMILIES = ["i3.xlarge"]
ALL_INSTANCE_TYPES = MEMORY_FAMILIES + CPU_FAMILIES + STORAGE_FAMILIES
AZS = ["us-east-1a", "us-east-1b", "us-east-1c", "us-east-1d"]

NORMAL_JOB_IDS = [
    "daily-sales-etl",
    "clickstream-aggregation",
    "recommendation-model-training",
    "financial-reconciliation",
    "catalog-enrichment",
    "fraud-pipeline",
]


def _pool_id(instance_type: str, az: str) -> str:
    return f"pool-{instance_type}-{az}"


def _event(
    finished_at: datetime,
    job_id: str,
    pool_id: str,
    status: Status,
    reason: Reason | None = None,
) -> dict:
    return {
        "finished_at": finished_at.isoformat(),
        "job_id": job_id,
        "pool_id": pool_id,
        "status": status.value,
        "reason": reason.value if reason else None,
    }


def _diurnal_weight(hour: int) -> float:
    """Fator de intensidade de jobs por hora do dia — picos às 9h e 13h,
    madrugada quieta. Modela o requisito de que o volume de jobs varia
    bastante ao longo do dia."""
    morning_peak = max(0.0, 1 - abs(hour - 9) / 4)
    afternoon_peak = max(0.0, 1 - abs(hour - 13) / 4)
    base = 0.15
    return base + max(morning_peak, afternoon_peak)


# --- cenário 1: AZ em degradação ao longo do dia -----------------------------


def generate_degrading_az_scenario(start: datetime, hours: int, rng: random.Random) -> list[dict]:
    """us-east-1c começa o período com ~98% de sucesso e cai para ~60% nas
    últimas 6 horas — simula uma AZ perdendo disponibilidade de spot ao
    longo do dia. Prova que o decaimento por idade do evento (Etapa 2) faz
    a API reagir à mudança recente, não à média histórica."""
    events = []
    instance_type = "r6.xlarge"
    az = "us-east-1c"
    pool_id = _pool_id(instance_type, az)

    for h in range(hours):
        hour_moment = start + timedelta(hours=h)
        # hours_until_end: 0 na última hora do dataset, subindo a partir daí
        hours_until_end = hours - 1 - h
        # taxa de sucesso cai de 98% para 60% só nas últimas 6h
        if hours_until_end < 6:
            success_rate = 0.98 - (5 - hours_until_end) / 5 * 0.38
        else:
            success_rate = 0.98

        n_events = rng.randint(10, 16)  # volume maior: o efeito precisa se sobrepor ao ruído
        for _ in range(n_events):
            ts = hour_moment + timedelta(minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
            job_id = rng.choice(NORMAL_JOB_IDS)
            if rng.random() < success_rate:
                events.append(_event(ts, job_id, pool_id, Status.SUCCESS))
            else:
                events.append(
                    _event(ts, job_id, pool_id, Status.FAILED, Reason.SPOT_INSTANCE_TERMINATION)
                )
    return events


# --- cenário 2: workhorse confiável e de alto volume --------------------------


def generate_workhorse_scenario(start: datetime, hours: int, rng: random.Random) -> list[dict]:
    """pool-r6.xlarge-us-east-1a: ~500 eventos, 97% de sucesso, distribuído
    de forma constante pelo dia. Deve vencer o 'novato sortudo' do cenário 3
    apesar de não ter 100% de sucesso — é a comparação central do README."""
    events = []
    pool_id = _pool_id("r6.xlarge", "us-east-1a")

    for h in range(hours):
        hour_moment = start + timedelta(hours=h)
        n_events = max(1, round(20 * _diurnal_weight(hour_moment.hour % 24)))
        for _ in range(n_events):
            ts = hour_moment + timedelta(minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
            job_id = rng.choice(NORMAL_JOB_IDS)
            if rng.random() < 0.97:
                events.append(_event(ts, job_id, pool_id, Status.SUCCESS))
            else:
                events.append(
                    _event(ts, job_id, pool_id, Status.FAILED, Reason.SPOT_INSTANCE_TERMINATION)
                )
    return events


# --- cenário 3: novato sortudo -------------------------------------------------


def generate_lucky_newcomer_scenario(start: datetime, hours: int, rng: random.Random) -> list[dict]:
    """pool-r6.2xlarge-us-east-1d: só 2 eventos, ambos SUCCESS — taxa ingênua
    de 100%. Sem correção para amostra pequena, este pool venceria o
    workhorse (97% com 500 amostras). É o teste que prova que o sistema de
    pontos com cortesia funciona."""
    pool_id = _pool_id("r6.2xlarge", "us-east-1d")
    # os dois eventos acontecem nas últimas 2 horas, para pesarem o máximo possível
    moments = [
        start + timedelta(hours=hours - 2, minutes=10),
        start + timedelta(hours=hours - 1, minutes=30),
    ]
    return [_event(m, rng.choice(NORMAL_JOB_IDS), pool_id, Status.SUCCESS) for m in moments]


# --- cenário 4: patologia de job (não do pool) ---------------------------------


def generate_pathological_job_scenario(
    start: datetime, hours: int, rng: random.Random
) -> list[dict]:
    """Um job mal escrito ('bad-etl-job') falha ~80 vezes por TIMED_OUT e
    SPARK_EXECUTION_ERROR, concentrado no pool c6.xlarge-us-east-1b — que é,
    de resto, um pool saudável (também recebe execuções normais de outros
    jobs). Prova que excluir essas razões do denominador impede que um job
    ruim derrube o score de um pool bom."""
    events = []
    pool_id = _pool_id("c6.xlarge", "us-east-1b")

    # falhas do job problemático, espalhadas pelo período
    for _ in range(80):
        h = rng.randint(0, hours - 1)
        ts = start + timedelta(hours=h, minutes=rng.randint(0, 59))
        reason = rng.choice([Reason.TIMED_OUT, Reason.SPARK_EXECUTION_ERROR])
        events.append(_event(ts, "bad-etl-job", pool_id, Status.FAILED, reason))

    # execuções normais e saudáveis de outros jobs no mesmo pool
    for h in range(hours):
        hour_moment = start + timedelta(hours=h)
        n_events = max(1, round(8 * _diurnal_weight(hour_moment.hour % 24)))
        for _ in range(n_events):
            ts = hour_moment + timedelta(minutes=rng.randint(0, 59))
            job_id = rng.choice(NORMAL_JOB_IDS)
            if rng.random() < 0.96:
                events.append(_event(ts, job_id, pool_id, Status.SUCCESS))
            else:
                events.append(
                    _event(ts, job_id, pool_id, Status.FAILED, Reason.SPOT_INSTANCE_TERMINATION)
                )
    return events


# --- cenário 5: cold start ------------------------------------------------------
#
# i3.xlarge-us-east-1a simplesmente não recebe nenhum evento no dataset —
# não requer código gerador, só precisa estar ausente. Documentado aqui
# para ficar claro que a ausência é intencional, não um esquecimento.
COLD_START_POOL = _pool_id("i3.xlarge", "us-east-1a")


# --- ruído de fundo: demais pools, textura realista ----------------------------


def generate_background_noise(start: datetime, hours: int, rng: random.Random) -> list[dict]:
    """Preenche os demais pools (famílias x AZs não cobertas pelos cenários
    acima) com atividade moderada e taxas de sucesso plausíveis, para o
    dataset não parecer artificialmente vazio fora dos 5 cenários."""
    events = []
    already_used_pools = {
        _pool_id("r6.xlarge", "us-east-1c"),
        _pool_id("r6.xlarge", "us-east-1a"),
        _pool_id("r6.2xlarge", "us-east-1d"),
        _pool_id("c6.xlarge", "us-east-1b"),
        COLD_START_POOL,
    }
    combinations = [
        (instance_type, az)
        for instance_type in ALL_INSTANCE_TYPES
        for az in AZS
        if _pool_id(instance_type, az) not in already_used_pools
    ]

    for h in range(hours):
        hour_moment = start + timedelta(hours=h)
        weight = _diurnal_weight(hour_moment.hour % 24)
        for instance_type, az in combinations:
            if rng.random() > 0.6:  # nem todo pool tem atividade toda hora
                continue
            n_events = max(0, round(rng.randint(1, 4) * weight))
            pool_id = _pool_id(instance_type, az)
            success_rate = rng.uniform(0.90, 0.99)  # cada pool tem uma saúde própria, mas estável
            for _ in range(n_events):
                ts = hour_moment + timedelta(minutes=rng.randint(0, 59))
                job_id = rng.choice(NORMAL_JOB_IDS)
                if rng.random() < success_rate:
                    events.append(_event(ts, job_id, pool_id, Status.SUCCESS))
                else:
                    reason = rng.choice(
                        [
                            Reason.SPOT_INSTANCE_TERMINATION,
                            Reason.SPOT_INSTANCE_TERMINATION,  # mais provável que as outras
                            Reason.TIMED_OUT,
                            Reason.SPARK_EXECUTION_ERROR,
                        ]
                    )
                    events.append(_event(ts, job_id, pool_id, Status.FAILED, reason))
    return events


def generate_dataset(hours: int, seed: int, now: datetime | None = None) -> list[dict]:
    """Monta o dataset completo combinando os 5 cenários e o ruído de fundo."""
    rng = random.Random(seed)
    now = now or datetime.now(UTC).replace(microsecond=0)
    start = now - timedelta(hours=hours)

    events = []
    events += generate_degrading_az_scenario(start, hours, rng)
    events += generate_workhorse_scenario(start, hours, rng)
    events += generate_lucky_newcomer_scenario(start, hours, rng)
    events += generate_pathological_job_scenario(start, hours, rng)
    events += generate_background_noise(start, hours, rng)

    events.sort(key=lambda e: e["finished_at"])
    return events


def write_partitioned(events: list[dict], out_dir: Path) -> None:
    """Escreve os eventos em <out_dir>/<AAAA-MM-DD>/<HH>.jsonl — um objeto
    por hora, imitando o particionamento típico de um bucket S3 alimentado
    por um processo contínuo."""
    by_partition: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        ts = datetime.fromisoformat(event["finished_at"])
        date = ts.strftime("%Y-%m-%d")
        hour = ts.strftime("%H")
        by_partition[(date, hour)].append(event)

    for (date, hour), group in by_partition.items():
        folder = out_dir / date
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{hour}.jsonl"
        with path.open("w") as f:
            for event in group:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/events"), help="pasta de saída")
    parser.add_argument("--hours", type=int, default=48, help="janela de tempo simulada, em horas")
    parser.add_argument("--seed", type=int, default=42, help="semente para reprodutibilidade")
    parser.add_argument(
        "--now",
        type=datetime.fromisoformat,
        default=None,
        help="instante final da janela simulada, ISO 8601 (padrão: agora)."
        " Fixar este valor torna a saída totalmente determinística — mesmo os"
        " nomes dos arquivos de partição, que dependem do instante final.",
    )
    args = parser.parse_args()

    now = args.now.replace(tzinfo=UTC) if args.now and args.now.tzinfo is None else args.now
    events = generate_dataset(hours=args.hours, seed=args.seed, now=now)
    write_partitioned(events, args.out)

    print(
        f"Gerados {len(events)} eventos em {args.out}/ (semente={args.seed}, janela={args.hours}h)"
    )


if __name__ == "__main__":
    main()
