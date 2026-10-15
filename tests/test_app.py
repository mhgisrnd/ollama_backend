from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_and_openapi_contract():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        schema = client.get("/openapi.json").json()
        assert "/api/v1/health" in schema["paths"]
        assert client.get("/docs").status_code == 200


def test_environment_overrides_settings(monkeypatch):
    monkeypatch.setenv("LLM_SERVER_APP_NAME", "Test server")
    settings = Settings(_env_file=None)
    assert create_app(settings).title == "Test server"
