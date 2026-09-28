"""
Testes do gerador de dados sintéticos.

Provam que os 5 cenários plantados (Etapa 1) têm de fato as características
que o algoritmo de scoring (Etapa 2) precisa para se comportar de forma
não-trivial, e que a geração é determinística.
"""

from datetime import UTC, datetime

from app.tools.generate_events import (
    COLD_START_POOL,
    generate_dataset,
    write_partitioned,
)

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def test_generation_is_deterministic_with_same_seed():
    d1 = generate_dataset(hours=48, seed=42, now=FIXED_NOW)
    d2 = generate_dataset(hours=48, seed=42, now=FIXED_NOW)
    assert d1 == d2


def test_different_seeds_generate_different_datasets():
    d1 = generate_dataset(hours=48, seed=1, now=FIXED_NOW)
    d2 = generate_dataset(hours=48, seed=2, now=FIXED_NOW)
    assert d1 != d2


def test_all_pool_ids_follow_the_expected_format():
    events = generate_dataset(hours=24, seed=42, now=FIXED_NOW)
    for e in events:
        assert e["pool_id"].startswith("pool-")
        parts = e["pool_id"].removeprefix("pool-").rsplit("-", 1)
        assert len(parts) == 2, f"pool_id fora do formato: {e['pool_id']}"


def test_workhorse_scenario_has_high_volume_and_high_reliability():
    events = generate_dataset(hours=48, seed=42, now=FIXED_NOW)
    workhorse = [e for e in events if e["pool_id"] == "pool-r6.xlarge-us-east-1a"]
    successes = sum(1 for e in workhorse if e["status"] == "SUCCESS")

    assert len(workhorse) > 300, "workhorse precisa de volume alto para o teste de amostra pequena"
    assert 0.93 < successes / len(workhorse) < 0.99


def test_lucky_newcomer_scenario_has_few_events_all_successful():
    events = generate_dataset(hours=48, seed=42, now=FIXED_NOW)
    newcomer = [e for e in events if e["pool_id"] == "pool-r6.2xlarge-us-east-1d"]

    assert len(newcomer) == 2
    assert all(e["status"] == "SUCCESS" for e in newcomer)


def test_degrading_az_scenario_worsens_in_the_last_hours():
    events = generate_dataset(hours=48, seed=42, now=FIXED_NOW)
    pool = [e for e in events if e["pool_id"] == "pool-r6.xlarge-us-east-1c"]
    pool.sort(key=lambda e: e["finished_at"])

    half = len(pool) // 2
    first_half, second_half = pool[:half], pool[half:]
    n_success_first = sum(1 for e in first_half if e["status"] == "SUCCESS")
    n_success_second = sum(1 for e in second_half if e["status"] == "SUCCESS")
    initial_rate = n_success_first / len(first_half)
    final_rate = n_success_second / len(second_half)

    assert final_rate < initial_rate, "a AZ deveria degradar ao longo do tempo"


def test_pathological_job_scenario_does_not_count_as_pool_failure():
    events = generate_dataset(hours=48, seed=42, now=FIXED_NOW)
    bad_job = [e for e in events if e["pool_id"] == "pool-c6.xlarge-us-east-1b" and e["job_id"] == "bad-etl-job"]

    assert len(bad_job) > 50
    assert all(e["status"] == "FAILED" for e in bad_job)
    assert all(e["reason"] in ("TIMED_OUT", "SPARK_EXECUTION_ERROR") for e in bad_job)

    # Essas falhas não devem ser SPOT_INSTANCE_TERMINATION.
    # Caso contrário, o teste da Etapa 2 sobre a exclusão de job_fault
    # perderia o sentido.
    assert not any(e["reason"] == "SPOT_INSTANCE_TERMINATION" for e in bad_job)


def test_cold_start_scenario_pool_does_not_appear_in_dataset():
    events = generate_dataset(hours=48, seed=42, now=FIXED_NOW)
    assert not any(e["pool_id"] == COLD_START_POOL for e in events)


def test_write_partitioned_generates_one_file_per_hour(tmp_path):
    events = generate_dataset(hours=3, seed=42, now=FIXED_NOW)
    write_partitioned(events, tmp_path)

    files = list(tmp_path.rglob("*.jsonl"))
    assert len(files) > 0
    # cada arquivo deve estar em <data>/<hora>.jsonl
    for file in files:
        assert file.parent.parent == tmp_path
        assert len(file.stem) == 2  # "HH"
