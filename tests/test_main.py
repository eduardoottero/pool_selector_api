"""
Testes de fumaça da aplicação — provam que a API sobe e responde.

Usa o TestClient com o lifespan real, então o refresh_loop roda de verdade
contra o EVENT_SOURCE configurado no ambiente de teste (local, apontando
para data/events por padrão). Testes que dependem de um estado específico
do snapshot ficam em test_routes.py, que publica um snapshot controlado
diretamente no snapshot_store — mais rápido e não depende de dados no disco.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_health_responds_ok():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_docs_available():
    """Swagger automático do FastAPI cobre o requisito de documentação do endpoint."""
    with TestClient(app) as client:
        response = client.get("/docs")
    assert response.status_code == 200


def test_openapi_lists_both_pool_endpoints():
    """O enunciado usa /get-pool num trecho e /get-pools noutro — ambos devem existir."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    paths = response.json()["paths"]
    assert "/get-pools" in paths
    assert "/get-pool" in paths
