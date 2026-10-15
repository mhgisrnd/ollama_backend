import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

BASE = "/api/v1/clients/pc-a"
BODY = {"client_id": "pc-a", "messages": [{"role": "user", "content": "레이어 목록 알려줘"}]}


def register(client):
    client.put(BASE, json={"display_name": "PC A", "app_version": "1"}).raise_for_status()
    client.put(BASE + "/tools", json={"tools": [{
        "name": name, "description": name, "source": source,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    } for name, source in (("get_layer_list", "python"), ("photoshop_ping", "photoshop_mcp"))]}).raise_for_status()


def model_response(content="", calls=None):
    return httpx.Response(200, json={"model": "test", "done": True,
        "message": {"role": "assistant", "content": content, **({"tool_calls": calls} if calls is not None else {})}})


def tool_call(name="get_layer_list", args=None):
    return {"function": {"name": name, "arguments": {} if args is None else args}}


def make_client(handler):
    return TestClient(create_app(Settings(_env_file=None, ollama_model="test"), transport=httpx.MockTransport(handler)))


def test_real_ws_roundtrip_with_mocked_model():
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            assert {item["function"]["name"] for item in body["tools"]} == {"get_layer_list", "photoshop_ping"}
            return model_response(calls=[tool_call()])
        assert body["messages"][-1]["role"] == "tool"
        data = json.loads(body["messages"][-1]["content"])
        assert data["result"]["count"] == 1
        assert not any(tool["function"]["name"] == "get_layer_list" for tool in body["tools"])
        return model_response("레이어 1개가 있습니다.")
    with make_client(handler) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(max_workers=1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=BODY)
            message = ws.receive_json()
            assert message["tool_name"] == "get_layer_list"
            ws.send_json({"type": "tool_result", "call_id": message["call_id"], "status": "succeeded",
                          "result": {"count": 1, "layers": [{"name": "ortho.tif"}]}})
            response = pending.result(timeout=5)
            assert response.status_code == 200
            assert response.json()["message"]["content"] == "현재 레이어는 총 1개입니다."
            assert response.json()["tool_results"][0]["call_id"] == message["call_id"]
            assert len(requests) == 1


def test_invalid_batch_is_rejected_before_any_execution():
    def handler(request):
        return model_response(calls=[tool_call(), tool_call("execute_script")])
    with make_client(handler) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            response = client.post("/api/v1/agent/chat", json=BODY)
            assert response.status_code == 502
            assert response.json()["detail"]["code"] == "invalid_tool_call"
            assert client.get("/api/v1/connections").json()[0]["pending_calls"] == 0


def test_final_model_failure_preserves_execution_trace():
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return model_response(calls=[tool_call()])
        raise httpx.ReadTimeout("timeout", request=request)
    with make_client(handler) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(max_workers=1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json={**BODY, "messages": [
                {"role": "user", "content": "레이어 목록과 포토샵 연결 상태 알려줘"}]})
            call = ws.receive_json()
            ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded", "result": {"layers": [], "count": 0}})
            result = pending.result(timeout=5).json()
            assert result["warning"] == "ollama_timeout"
            assert result["tool_results"][0]["status"] == "succeeded"


def test_failure_stops_remaining_tools_and_no_retry():
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return model_response(calls=[tool_call(), tool_call("photoshop_ping")])
        body = json.loads(request.content)
        assert body["tools"] == []
        assert [message["role"] for message in body["messages"][-2:]] == ["tool", "tool"]
        return model_response("조회에 실패했습니다.")
    with make_client(handler) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(max_workers=1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=BODY)
            call = ws.receive_json()
            ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "failed", "error": "query failed"})
            result = pending.result(timeout=5).json()
            assert len(result["tool_results"]) == 2
            assert result["tool_results"][1]["error"].startswith("skipped_after_previous_failure")
            assert count == 1


def test_offline_fails_before_model_request():
    def handler(request):
        raise AssertionError("No model request while offline")
    with make_client(handler) as client:
        assert client.post("/api/v1/agent/chat", json=BODY).status_code == 503


def test_plain_answer_has_no_fabricated_execution_trace():
    with make_client(lambda request: model_response("안녕하세요.")) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            response = client.post("/api/v1/agent/chat", json=BODY)
            assert response.status_code == 200
            assert response.json()["tool_results"] == []


def test_duplicate_tool_calls_rejected_without_dispatch():
    with make_client(lambda request: model_response(calls=[tool_call(), tool_call()])) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            assert client.post("/api/v1/agent/chat", json=BODY).status_code == 502
            assert client.get("/api/v1/connections").json()[0]["pending_calls"] == 0


@pytest.mark.parametrize("first_timeout", [False, True])
def test_followup_after_completion_or_model_timeout_releases_request_state(first_timeout):
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if first_timeout and len(requests) == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        latest = body["messages"][-1]["content"]
        assert len(body["messages"]) == 2  # system + current query, no stale success prose
        return model_response(calls=[tool_call("photoshop_ping" if "포토샵" in latest else "get_layer_list")])

    with make_client(handler) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(max_workers=1) as pool:
            ws.receive_json()
            first = pool.submit(client.post, "/api/v1/agent/chat", json=BODY)
            if not first_timeout:
                call = ws.receive_json()
                ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded",
                              "result": {"count": 92, "layers": []}})
            response = first.result(timeout=5)
            assert response.status_code == (504 if first_timeout else 200)
            assert "pc-a" not in client.app.state.agent.busy
            assert client.get("/api/v1/connections").json()[0]["pending_calls"] == 0
            history = BODY["messages"] + ([response.json()["message"]] if not first_timeout else [])
            second = pool.submit(client.post, "/api/v1/agent/chat", json={"client_id": "pc-a", "messages":
                history + [{"role": "user", "content": "포토샵 연결도 확인해줘"}]})
            call = ws.receive_json()
            assert call["tool_name"] == "photoshop_ping"
            ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded",
                          "result": {"connected": True}})
            result = second.result(timeout=5)
            assert result.status_code == 200
            assert result.json()["requested_tools"] == ["photoshop_ping"]
            assert result.json()["completion_status"] == "completed"
            assert len(requests) == 2
            assert "pc-a" not in client.app.state.agent.busy


def test_overlapping_request_is_rejected_then_next_request_can_run():
    with make_client(lambda request: model_response(calls=[tool_call()])) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(max_workers=1) as pool:
            ws.receive_json()
            first = pool.submit(client.post, "/api/v1/agent/chat", json=BODY)
            call = ws.receive_json()
            overlap = client.post("/api/v1/agent/chat", json=BODY)
            assert overlap.status_code == 409
            assert overlap.json()["detail"]["code"] == "agent_busy"
            ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded",
                          "result": {"count": 1, "layers": []}})
            assert first.result(timeout=5).status_code == 200
            second = pool.submit(client.post, "/api/v1/agent/chat", json=BODY)
            next_call = ws.receive_json()
            assert next_call["call_id"] != call["call_id"]
            ws.send_json({"type": "tool_result", "call_id": next_call["call_id"], "status": "succeeded",
                          "result": {"count": 2, "layers": []}})
            assert second.result(timeout=5).json()["message"]["content"] == "현재 레이어는 총 2개입니다."
