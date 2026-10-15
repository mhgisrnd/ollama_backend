from concurrent.futures import ThreadPoolExecutor
import json

from app.agent.coverage import request_scope
from app.schemas.chat import ChatMessage
from test_agent import BASE, register, make_client, model_response, tool_call

COMPOUND = {"client_id": "pc-a", "messages": [{"role": "user", "content": "현재 레이어 목록과 포토샵 연결 상태를 알려줘"}]}


def reply(ws, name):
    call = ws.receive_json()
    assert call["tool_name"] == name
    result = {"count": 92, "layers": []} if name == "get_layer_list" else {"connected": True}
    ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded", "result": result})


def test_missing_tool_gets_one_recovery_and_both_actual_results():
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return model_response(calls=[tool_call()])
        if len(requests) == 2:
            return model_response("레이어와 포토샵 확인을 모두 완료했습니다.")
        if len(requests) == 3:
            assert [item["function"]["name"] for item in body["tools"]] == ["photoshop_ping"]
            return model_response(calls=[tool_call("photoshop_ping")])
        return model_response("English draft or incorrect model summary")
    with make_client(handler) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(max_workers=1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=COMPOUND)
            reply(ws, "get_layer_list")
            reply(ws, "photoshop_ping")
            data = pending.result(timeout=5).json()
            assert data["completion_status"] == "completed"
            assert data["missing_tools"] == []
            assert len(data["tool_results"]) == 2
            assert "92개" in data["message"]["content"]
            assert "포토샵 통신에 성공했습니다." in data["message"]["content"]
            assert len(requests) == 3


def test_ignored_recovery_is_partial_and_does_not_claim_photoshop_success():
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return model_response(calls=[tool_call()]) if calls == 1 else model_response("포토샵 연결 확인이 성공했습니다.")
    with make_client(handler) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(max_workers=1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=COMPOUND)
            reply(ws, "get_layer_list")
            data = pending.result(timeout=5).json()
            assert calls == 3
            assert data["completion_status"] == "partial"
            assert data["missing_tools"] == ["photoshop_ping"]
            assert data["warning"] == "partial_completion"
            assert "미완료: 포토샵 연결 확인" in data["message"]["content"]
            assert "포토샵 연결 확인이 성공" not in data["message"]["content"]


def test_negation_and_latest_user_turn_scope():
    requested, excluded = request_scope([ChatMessage(role="user", content="포토샵은 확인하지 말고 레이어 목록만 알려줘")])
    assert requested == {"get_layer_list"}
    assert excluded == {"photoshop_ping"}
    requested, _ = request_scope([ChatMessage(role="user", content="레이어와 포토샵 연결 상태 알려줘"),
                                  ChatMessage(role="assistant", content="확인했습니다"),
                                  ChatMessage(role="user", content="안녕")])
    assert requested == set()


def test_explicitly_excluded_tool_is_never_executed():
    with make_client(lambda request: model_response(calls=[tool_call("photoshop_ping")])) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            response = client.post("/api/v1/agent/chat", json={**COMPOUND, "messages": [{
                "role": "user", "content": "포토샵은 확인하지 말고 레이어 목록만 알려줘"}]})
            assert response.status_code == 502
            assert client.get("/api/v1/connections").json()[0]["pending_calls"] == 0
