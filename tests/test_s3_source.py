"""Testes do adapter S3 usando moto — mocka a API do boto3 inteiramente em
memória, sem precisar de rede, daemon do Docker nem credenciais reais.

Isso é o que permite afirmar que o caminho do S3 é código genuinamente
testado em CI, não apenas escrito e nunca exercitado — mesmo sem uma conta
AWS disponível (ver a decisão registrada no plano do projeto).
"""

import boto3
import pytest
from moto import mock_aws

from app.ingestion.sources import S3EventSource


@pytest.fixture
def s3_bucket():
    """Sobe um bucket S3 falso (em memória, via moto) para cada teste."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield client


def test_list_objects_empty_bucket_returns_empty_list(s3_bucket):
    source = S3EventSource(bucket="test-bucket", prefix="events/", region="us-east-1")
    assert source.list_objects() == []


def test_list_objects_finds_objects_under_prefix(s3_bucket):
    s3_bucket.put_object(Bucket="test-bucket", Key="events/2026-01-15/10.jsonl", Body=b'{"a": 1}')
    s3_bucket.put_object(Bucket="test-bucket", Key="events/2026-01-15/11.jsonl", Body=b'{"a": 2}')
    s3_bucket.put_object(Bucket="test-bucket", Key="outro-prefixo/arquivo.txt", Body=b"ignorar")

    source = S3EventSource(bucket="test-bucket", prefix="events/", region="us-east-1")
    refs = source.list_objects()

    keys = {ref.key for ref in refs}
    assert keys == {"events/2026-01-15/10.jsonl", "events/2026-01-15/11.jsonl"}


def test_list_objects_version_is_the_etag(s3_bucket):
    s3_bucket.put_object(Bucket="test-bucket", Key="events/10.jsonl", Body=b'{"a": 1}')

    source = S3EventSource(bucket="test-bucket", prefix="events/", region="us-east-1")
    ref = source.list_objects()[0]

    # o ETag do S3 real vem entre aspas; o adapter deve devolvê-lo sem elas
    assert '"' not in ref.version
    assert len(ref.version) > 0


def test_read_lines_returns_object_content_split_by_line(s3_bucket):
    s3_bucket.put_object(Bucket="test-bucket", Key="events/10.jsonl", Body=b'{"a": 1}\n{"a": 2}\n')

    source = S3EventSource(bucket="test-bucket", prefix="events/", region="us-east-1")
    ref = source.list_objects()[0]

    lines = source.read_lines(ref)
    assert lines == ['{"a": 1}', '{"a": 2}']


def test_list_objects_paginates_beyond_default_page_size(s3_bucket):
    """A API list_objects_v2 pagina em blocos de até 1000 objetos por
    página — testa que o paginator do boto3 percorre todas as páginas,
    não só a primeira."""
    for i in range(5):
        s3_bucket.put_object(Bucket="test-bucket", Key=f"events/{i:04d}.jsonl", Body=b"{}")

    source = S3EventSource(bucket="test-bucket", prefix="events/", region="us-east-1")
    refs = source.list_objects()

    assert len(refs) == 5


def test_build_event_source_selects_s3_adapter_from_settings():
    from app.core.config import Settings
    from app.ingestion.sources import S3EventSource, build_event_source

    settings = Settings(event_source="s3", s3_bucket="my-bucket")
    source = build_event_source(settings)

    assert isinstance(source, S3EventSource)
    assert source.bucket == "my-bucket"


def test_build_event_source_selects_local_adapter_from_settings():
    from app.core.config import Settings
    from app.ingestion.sources import LocalFileEventSource, build_event_source

    settings = Settings(event_source="local")
    source = build_event_source(settings)

    assert isinstance(source, LocalFileEventSource)


def test_build_event_source_raises_on_unknown_source():
    from app.core.config import Settings
    from app.ingestion.sources import build_event_source

    settings = Settings(event_source="ftp")  # inexistente de propósito
    with pytest.raises(ValueError):
        build_event_source(settings)
