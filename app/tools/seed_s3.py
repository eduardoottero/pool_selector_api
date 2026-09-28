"""
Sobe o dataset sintético local para um bucket S3 (real ou LocalStack).

Usado pelo docker-compose.yml (perfil aws, serviço seeder) para popular o bucket
antes da API subir apontando `EVENT_SOURCE=s3` para ele.
Preserva o mesmo layout particionado por hora do gerador (Etapa 1), então
o S3EventSource lê exatamente a mesma estrutura que o LocalFileEventSource já lê do disco, só muda de onde os bytes vêm.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import boto3

from app.core.config import settings


def ensure_bucket(client, bucket: str, region: str) -> None:
    """
    Cria o bucket se ele ainda não existir — idempotente,
    então rodar o seeder de novo num bucket já populado não falha.
    """
    existing = {b["Name"] for b in client.list_buckets()["Buckets"]}
    if bucket in existing:
        return
    if region == "us-east-1":
        # a API do S3 trata us-east-1 como caso especial: não aceita LocationConstraint para a região "padrão"
        client.create_bucket(Bucket=bucket)
    else:
        client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})


def upload_dataset(client, bucket: str, prefix: str, source_dir: Path) -> int:
    """
    Envia cada arquivo .jsonl mantendo a mesma estrutura de pastas
    relativa a source_dir, prefixada por `prefix` (ex: events/).
    """
    uploaded = 0
    for path in sorted(source_dir.rglob("*.jsonl")):
        relative_key = path.relative_to(source_dir).as_posix()
        key = f"{prefix.rstrip('/')}/{relative_key}"
        client.upload_file(str(path), bucket, key)
        uploaded += 1
    return uploaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(settings.local_events_dir),
        help="pasta local com os arquivos .jsonl a enviar",
    )
    args = parser.parse_args()

    client = boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )

    ensure_bucket(client, settings.s3_bucket, settings.aws_region)
    count = upload_dataset(client, settings.s3_bucket, settings.s3_prefix, args.source)

    print(f"{count} arquivos enviados para s3://{settings.s3_bucket}/{settings.s3_prefix}")


if __name__ == "__main__":
    main()
