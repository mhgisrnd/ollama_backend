from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.registry import TOOL_EXAMPLE

CLIENT = {"display_name": "테스트 벡터 프로그램", "app_version": "1.0.0"}
ROOT = "/api/v1/clients"


def test_registration_replacement_isolation_and_restart():
    settings = Settings(_env_file=None)
    with TestClient(create_app(settings)) as client:
        assert client.get(ROOT).json() == []
        first = client.put(f"{ROOT}/pc-a", json=CLIENT)
        assert first.status_code == 200
        assert first.json()["client_id"] == "pc-a"
        client.put(f"{ROOT}/pc-b", json=CLIENT).raise_for_status()
        assert client.get(f"{ROOT}/pc-a/tools").json()["revision"] == 0
        saved = client.put(f"{ROOT}/pc-a/tools", json=TOOL_EXAMPLE)
        assert saved.status_code == 200
        assert saved.json()["revision"] == 1
        assert client.put(f"{ROOT}/pc-a/tools", json=TOOL_EXAMPLE).json() == saved.json()
        assert client.get(f"{ROOT}/pc-b/tools").json()["tools"] == []
        client.put(f"{ROOT}/pc-a", json={**CLIENT, "app_version": "2.0"}).raise_for_status()
        assert client.get(f"{ROOT}/pc-a/tools").json() == saved.json()
    with TestClient(create_app(settings)) as client:
        assert len(client.get(ROOT).json()) == 2
        assert client.get(f"{ROOT}/pc-a/tools").json() == saved.json()
        cleared = client.put(f"{ROOT}/pc-a/tools", json={"tools": []}).json()
        assert cleared["tools"] == []
        assert cleared["revision"] == 2


@pytest.mark.parametrize("schema", [
    {"type": "string"},
    {"type": "object", "properties": {"x": {"type": "bogus"}}},
    {"type": "object", "required": ["undefined"]},
    {"type": "object", "properties": {"x": {"$ref": "https://example.org/schema"}}},
])
def test_bad_schema_preserves_previous_catalog(schema):
    with TestClient(create_app(Settings(_env_file=None))) as client:
        client.put(f"{ROOT}/pc-a", json=CLIENT).raise_for_status()
        saved = client.put(f"{ROOT}/pc-a/tools", json=TOOL_EXAMPLE).json()
        tool = {**TOOL_EXAMPLE["tools"][0], "input_schema": schema}
        response = client.put(f"{ROOT}/pc-a/tools", json={"tools": [tool]})
        assert response.status_code == 422
        assert client.get(f"{ROOT}/pc-a/tools").json() == saved


def test_missing_client_duplicate_names_and_invalid_registration():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get(f"{ROOT}/missing/tools").status_code == 404
        assert client.put(f"{ROOT}/missing/tools", json=TOOL_EXAMPLE).status_code == 404
        assert client.put(f"{ROOT}/bad.id", json=CLIENT).status_code == 422
        assert client.put(f"{ROOT}/pc-a", json={**CLIENT, "display_name": " "}).status_code == 422
        client.put(f"{ROOT}/pc-a", json=CLIENT).raise_for_status()
        assert client.put(f"{ROOT}/pc-a/tools", json={"tools": TOOL_EXAMPLE["tools"] * 2}).status_code == 422
        assert client.get(f"{ROOT}/pc-a/tools").json()["tools"] == []


def test_concurrent_replacements_leave_a_complete_catalog():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        client.put(f"{ROOT}/pc-a", json=CLIENT).raise_for_status()
        bodies = [{"tools": [{**TOOL_EXAMPLE["tools"][0], "name": f"tool_{i}"}]} for i in range(6)]
        with ThreadPoolExecutor(max_workers=6) as executor:
            responses = list(executor.map(lambda body: client.put(f"{ROOT}/pc-a/tools", json=body), bodies))
        assert all(response.status_code == 200 for response in responses)
        catalog = client.get(f"{ROOT}/pc-a/tools").json()
        assert catalog["revision"] == 6
        assert {"tools": catalog["tools"]} in bodies


def test_swagger_contains_registration_examples():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        schema = client.get("/openapi.json").json()
        assert "put" in schema["paths"][ROOT + "/{client_id}/tools"]
        assert schema["components"]["schemas"]["ToolRegistration"]["example"] == TOOL_EXAMPLE
