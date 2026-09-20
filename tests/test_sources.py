"""Testes do adapter de fonte de eventos local (disco).

O adapter S3 é testado com moto na Etapa 5 (junto com o Docker/LocalStack),
já que exige mockar a API do boto3 — aqui cobrimos só o adapter que o
`make dev` usa por padrão.
"""

from app.ingestion.sources import LocalFileEventSource


def test_list_objects_empty_dir_returns_empty_list(tmp_path):
    source = LocalFileEventSource(tmp_path / "nao-existe")
    assert source.list_objects() == []


def test_list_objects_finds_jsonl_files_recursively(tmp_path):
    (tmp_path / "2026-01-15").mkdir()
    (tmp_path / "2026-01-15" / "10.jsonl").write_text('{"a": 1}\n')
    (tmp_path / "2026-01-15" / "11.jsonl").write_text('{"a": 2}\n')
    (tmp_path / "readme.txt").write_text("ignorar isto")

    source = LocalFileEventSource(tmp_path)
    refs = source.list_objects()

    assert len(refs) == 2
    assert all(ref.key.endswith(".jsonl") for ref in refs)


def test_list_objects_version_changes_when_file_is_modified(tmp_path):
    file = tmp_path / "10.jsonl"
    file.write_text('{"a": 1}\n')

    source = LocalFileEventSource(tmp_path)
    version_before = source.list_objects()[0].version

    # força um mtime diferente (alguns filesystems têm resolução de 1s)
    import os
    import time

    time.sleep(0.01)
    os.utime(file, (time.time() + 10, time.time() + 10))

    version_after = source.list_objects()[0].version
    assert version_before != version_after


def test_read_lines_returns_file_content_split_by_line(tmp_path):
    file = tmp_path / "10.jsonl"
    file.write_text('{"a": 1}\n{"a": 2}\n')

    source = LocalFileEventSource(tmp_path)
    ref = source.list_objects()[0]

    lines = source.read_lines(ref)
    assert lines == ['{"a": 1}', '{"a": 2}']
