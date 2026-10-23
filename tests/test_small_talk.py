import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from test_agent import BASE, register


@pytest.mark.parametrize("mode, routing", [
    ("structured", {"operations": ["chat"]}),
    ("general", {"tasks": [{"tool": "chat", "request": "자기소개"}]}),
])
def test_chat_routing_answers_freely_without_tools(mode, routing):
    captured = []
    def handler(request):
        data = json.loads(request.content)
        captured.append(data)
        content = json.dumps(routing) if "format" in data else "안녕하세요. 레이어 조회를 도와드립니다."
        return httpx.Response(200, json={"model": "test", "done": True, "message": {"role": "assistant", "content": content}})
    app = create_app(Settings(_env_file=None, ollama_model="test", agent_mode=mode), transport=httpx.MockTransport(handler))
    with TestClient(app) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            data = client.post("/api/v1/agent/chat", json={"client_id": "pc-a", "messages": [
                {"role": "user", "content": "자기소개 해주세요"}]}).json()
    assert data["message"]["content"] == "안녕하세요. 레이어 조회를 도와드립니다."
    assert data["tool_results"] == [] and data["warning"] is None
    free = captured[-1]
    assert "format" not in free
    assert "수치를 추측해서 말하지 마세요" in free["messages"][0]["content"]
    assert free["messages"][-1]["content"] == "자기소개 해주세요"
