import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def client_for(handler):
    return TestClient(create_app(
        Settings(_env_file=None, ollama_model="test-model"),
        transport=httpx.MockTransport(handler),
    ))


def test_status_and_chat_forwarding():
    import json

    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test-version"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "test-model"}]})
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["stream"] is False
        assert body["options"] == {"num_ctx": 4096, "num_predict": 512}
        assert body["messages"][-1]["content"] == "안녕"
        return httpx.Response(200, json={
            "model": "test-model", "done": True,
            "message": {"role": "assistant", "content": "안녕하세요"},
        })

    with client_for(handler) as client:
        assert client.get("/api/v1/ollama/status").json()["model_available"] is True
        response = client.post("/api/v1/chat", json={"messages": [{"role": "user", "content": "안녕"}]})
        assert response.status_code == 200
        assert response.json()["message"]["content"] == "안녕하세요"
        assert response.json()["request_id"]


@pytest.mark.parametrize("kind,status,code", [
    ("connection", 503, "ollama_unavailable"),
    ("timeout", 504, "ollama_timeout"),
    ("missing", 502, "ollama_model_unavailable"),
    ("malformed", 502, "ollama_invalid_response"),
    ("upstream", 502, "ollama_upstream_error"),
])
def test_provider_errors(kind, status, code):
    def handler(request):
        if kind == "connection":
            raise httpx.ConnectError("unavailable", request=request)
        if kind == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if kind == "missing":
            return httpx.Response(404, json={"error": "missing"})
        if kind == "upstream":
            return httpx.Response(500, text="private error")
        return httpx.Response(200, json={"message": None})

    with client_for(handler) as client:
        response = client.post("/api/v1/chat", json={"messages": [{"role": "user", "content": "test"}]})
        assert response.status_code == status
        assert response.json()["detail"]["code"] == code
        assert client.get("/api/v1/health").status_code == 200


def test_invalid_input_does_not_call_ollama():
    def handler(request):
        raise AssertionError("Invalid input must not reach Ollama")

    with client_for(handler) as client:
        for body in ({"messages": []}, {"messages": [{"role": "tool", "content": "x"}]},
                     {"messages": [{"role": "user", "content": " "}]}):
            assert client.post("/api/v1/chat", json=body).status_code == 422


def test_qwen3_no_think_and_final_answer_only():
    import json
    def handler(request):
        body = json.loads(request.content)
        assert body["think"] is False
        assert body["messages"][-1]["content"].endswith("/no_think")
        return httpx.Response(200, json={"model": "qwen3:4b", "done": True,
            "message": {"role": "assistant", "content": "<think>hidden draft</think>완료했습니다."}})
    with TestClient(create_app(Settings(_env_file=None, ollama_model="qwen3:4b"), transport=httpx.MockTransport(handler))) as client:
        response = client.post("/api/v1/chat", json={"messages": [{"role": "user", "content": "안녕"}]})
        assert response.json()["message"]["content"] == "완료했습니다."


def test_length_limited_response_is_not_returned_as_final_answer():
    def handler(request):
        return httpx.Response(200, json={"model": "test", "done": True, "done_reason": "length",
            "message": {"role": "assistant", "content": "unfinished draft"}})
    with client_for(handler) as client:
        response = client.post("/api/v1/chat", json={"messages": [{"role": "user", "content": "안녕"}]})
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "ollama_output_truncated"
