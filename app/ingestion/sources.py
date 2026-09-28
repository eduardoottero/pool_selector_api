"""
Fonte de eventos: de onde a ingestão lê os arquivos JSONL.

Um Protocol (interface estrutural do Python) define o contrato, com duas implementações: 
leitura do disco local (padrão, usada pelo `make dev`, sem nenhuma dependência de nuvem) e 
leitura via boto3 de um bucket S3 real ou do LocalStack. 
As duas implementações usam exatamente o mesmo código de parsing, só muda de onde os bytes vêm. 
O caminho do S3 é código real, testado com moto (ver tests/test_s3_source.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ObjectRef:
    """
    Referência a um objeto de eventos (um arquivo local ou uma key do S3).

    `version` é usado para leitura incremental: no adapter local é o mtime do arquivo; 
    no S3 seria o ETag do objeto. Se a versão não mudou desde a última leitura, o refresher (Etapa 3) pode pular esse objeto.
    """

    key: str
    version: str


class EventSource(Protocol):
    """
    Contrato que qualquer fonte de eventos deve implementar.
    """

    def list_objects(self) -> list[ObjectRef]:
        """
        Lista todos os objetos de eventos disponíveis na fonte.
        """
        ...

    def read_lines(self, ref: ObjectRef) -> list[str]:
        """
        Lê as linhas JSONL de um objeto específico.
        """
        ...


class LocalFileEventSource:
    """
    Lê eventos de arquivos JSONL no disco local.

    É a fonte padrão do projeto — usada por `make dev` sem exigir nenhuma
    dependência de nuvem ou container. Espera o layout gerado pela Etapa 1: <base_dir>/<data>/<hora>.jsonl.
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def list_objects(self) -> list[ObjectRef]:
        if not self.base_dir.exists():
            return []
        return [
            ObjectRef(key=str(path), version=str(path.stat().st_mtime))
            for path in sorted(self.base_dir.rglob("*.jsonl"))
        ]

    def read_lines(self, ref: ObjectRef) -> list[str]:
        path = Path(ref.key)
        return path.read_text().splitlines()


class S3EventSource:
    """
    Lê eventos de um bucket S3 via boto3 — funciona tanto contra a AWS real quanto contra o LocalStack, mudando só endpoint_url.

    O parâmetro endpoint_url=None (padrão) faz o boto3 apontar para a AWS real; 
    passar a URL do LocalStack (ex: http://localhost:4566) redireciona todas as chamadas sem nenhuma mudança de código;
    é a mesma ideia da variável de ambiente AWS_ENDPOINT_URL em app/core/config.py.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        region: str = "us-east-1",
        endpoint_url: str | None = None,
    ):
        import boto3

        self.bucket = bucket
        self.prefix = prefix
        self._client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)

    def list_objects(self) -> list[ObjectRef]:
        objects: list[ObjectRef] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for obj in page.get("Contents", []):
                # ETag vem entre aspas na resposta do S3 (ex: '"abc123"')
                objects.append(ObjectRef(key=obj["Key"], version=obj["ETag"].strip('"')))
        return objects

    def read_lines(self, ref: ObjectRef) -> list[str]:
        response = self._client.get_object(Bucket=self.bucket, Key=ref.key)
        body = response["Body"].read().decode("utf-8")
        return body.splitlines()


def build_event_source(settings) -> EventSource:  # noqa: ANN001 - tipo importado só em runtime
    """
    Fábrica: escolhe o adapter conforme `settings.event_source`.

    Mantém a decisão de qual fonte usar centralizada num único lugar, 
    ao invés de espalhar if event_source == "local" pelo resto do código.
    """
    if settings.event_source == "local":
        return LocalFileEventSource(settings.local_events_dir)
    if settings.event_source == "s3":
        return S3EventSource(
            bucket=settings.s3_bucket,
            prefix=settings.s3_prefix,
            region=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        )
    raise ValueError(f"event_source desconhecido: {settings.event_source!r}")
