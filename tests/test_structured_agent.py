import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.experiments.evaluate_layer_query import CASES, FIXTURE
from test_agent import BASE, register


def client_for(plans):
    responses = iter(plans)
    def handler(request):
        assert "format" in json.loads(request.content)
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        if (isinstance(value, dict) and "source" in value
                and "steps" in json.loads(request.content)["format"].get("properties", {})):
            value = {"steps": [value]}
        return httpx.Response(200, json={"model": "test", "done": True, "message": {
            "role": "assistant", "content": json.dumps(value)}})
    return TestClient(create_app(Settings(_env_file=None, ollama_model="test", agent_mode="structured"),
                                 transport=httpx.MockTransport(handler)))


def body(question, session="chat-a"):
    return {"client_id": "pc-a", "session_id": session, "messages": [{"role": "user", "content": question}]}


def reply_layers(ws, rows=FIXTURE, count=None):
    call = ws.receive_json()
    assert call["tool_name"] == "get_layer_list"
    ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded",
                  "result": {"count": len(rows) if count is None else count, "layers": rows}})


def test_full_followup_sequence_uses_cached_rows_and_current_refresh():
    plans = [item for _, query in CASES for item in ({"operations": ["query_layers"]}, query)]
    with client_for(plans) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            counts = []
            for index, (question, query) in enumerate(CASES):
                pending = pool.submit(client.post, "/api/v1/agent/chat", json=body(question))
                if query["source"] == "current":
                    reply_layers(ws, FIXTURE + ([{"name": "new.tif", "visible": True}] if index == 4 else []))
                result = pending.result(timeout=5)
                assert result.status_code == 200, result.text
                data = result.json()
                assert data["completion_status"] == "completed"
                assert data["session_id"] == "chat-a"
                counts.append(data["query_result"]["count"])
                if query["output"] == "count":
                    assert data["query_result"]["layers"] == []
            assert counts == [6, 3, 2, 2, 7]


def test_new_session_and_reconnect_do_not_reuse_old_snapshot():
    plans = [{"operations": ["query_layers"]}, CASES[0][1],
             {"operations": ["query_layers"]}, CASES[1][1],
             {"operations": ["query_layers"]}, CASES[1][1]]
    with client_for(plans) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=body(CASES[0][0]))
            reply_layers(ws)
            assert pending.result(timeout=5).status_code == 200
            other = client.post("/api/v1/agent/chat", json=body(CASES[1][0], "chat-b")).json()
            assert other["warning"] == "previous_result_unavailable"
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            result = client.post("/api/v1/agent/chat", json=body(CASES[1][0])).json()
            assert result["warning"] == "previous_result_unavailable"


def test_incomplete_snapshot_not_counted_or_cached():
    with client_for([{"operations": ["query_layers"]}, CASES[0][1]]) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=body(CASES[0][0]))
            reply_layers(ws, count=99)
            data = pending.result(timeout=5).json()
            assert data["completion_status"] == "failed"
            assert data["warning"] == "incomplete_layer_snapshot"
            assert data["query_result"] is None
            assert not client.app.state.agent.structured.sessions


def test_unsupported_and_invalid_plans_never_dispatch():
    with client_for([{"operations": []}, {"operations": ["delete_all"]}]) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            data = client.post("/api/v1/agent/chat", json=body("레이어 삭제해줘")).json()
            assert data["tool_results"] == []
            assert data["warning"] == "clarification_required"
            assert client.post("/api/v1/agent/chat", json=body("삭제해줘")).status_code == 502
            assert not client.app.state.agent.busy


def test_compound_preserves_both_real_results_without_final_generation():
    with client_for([{"operations": ["query_layers", "photoshop_ping"]}, CASES[0][1]]) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=body("레이어 목록과 포토샵 연결 상태 알려줘"))
            reply_layers(ws)
            call = ws.receive_json()
            assert call["tool_name"] == "photoshop_ping"
            ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded", "result": {"connected": True}})
            data = pending.result(timeout=5).json()
            assert data["completion_status"] == "completed"
            assert "포토샵 통신에 성공했습니다." in data["message"]["content"]


def test_count_repair_happens_before_execution_and_timeout_releases_busy():
    wrong = {**CASES[0][1], "output": "list"}
    correct = {**wrong, "output": "count"}
    with client_for([{"operations": ["query_layers"]}, wrong, correct,
                     httpx.ReadTimeout("timeout"), {"operations": ["photoshop_ping"]}]) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=body("레이어 개수 알려줘"))
            reply_layers(ws)
            assert pending.result(timeout=5).json()["query_result"]["query"]["output"] == "count"
            assert client.post("/api/v1/agent/chat", json=body("포토샵 상태 알려줘")).status_code == 504
            assert not client.app.state.agent.busy
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=body("포토샵 상태 알려줘"))
            call = ws.receive_json()
            ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded", "result": {"connected": True}})
            assert pending.result(timeout=5).json()["completion_status"] == "completed"


def test_session_store_separates_clients_and_expires_snapshots():
    import time
    from types import SimpleNamespace
    from app.agent.structured import StructuredAgent
    from app.agent.layer_query import LayerQuery
    agent = StructuredAgent(set())
    connection = SimpleNamespace(connection_id="connection")
    first = SimpleNamespace(client_id="first", session_id="same")
    second = SimpleNamespace(client_id="second", session_id="same")
    key, session = agent.session(first, connection)
    session.query.execute(LayerQuery.model_validate(CASES[0][1]), lambda: FIXTURE)
    agent.remember(key, session)
    assert agent.session(first, connection)[1].query.previous_rows is not None
    assert agent.session(second, connection)[1].query.previous_rows is None
    agent.sessions[key].touched = time.monotonic() - 1801
    assert agent.session(first, connection)[1].query.previous_rows is None


def test_excluded_tool_and_overlapping_request_are_rejected_before_extra_execution():
    with client_for([{"operations": ["photoshop_ping"]}, {"operations": ["query_layers"]}, CASES[0][1]]) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            result = client.post("/api/v1/agent/chat", json=body("포토샵은 확인하지 말고 레이어 목록만 알려줘")).json()
            assert result["warning"] == "invalid_query_plan" and result["tool_results"] == []
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=body(CASES[0][0]))
            call = ws.receive_json()
            assert client.post("/api/v1/agent/chat", json=body(CASES[1][0])).status_code == 409
            ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded",
                          "result": {"count": len(FIXTURE), "layers": FIXTURE}})
            assert pending.result(timeout=5).json()["completion_status"] == "completed"


@pytest.mark.parametrize("second_source", ["previous_result", "current"])
def test_first_turn_full_list_and_filtered_count_share_one_snapshot(second_source):
    question = "현재 레이어 목록은 어떻고 그중 tif는 몇개인지 알려줘"
    count = {**CASES[1][1], "source": second_source}
    plans = [{"operations": ["query_layers"]},
             {"questions": ["현재 전체 레이어 목록 알려줘", "그중 tif는 몇 개야?"]},
             CASES[0][1], count]
    with client_for(plans) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=body(question))
            reply_layers(ws)
            data = pending.result(timeout=5).json()
            assert data["completion_status"] == "completed"
            assert "전체 레이어는 6개" in data["message"]["content"]
            assert "TIF/TIFF 레이어는 3개" in data["message"]["content"]
            queries = [item["result"] for item in data["tool_results"] if item["tool_name"] == "query_layers"]
            assert len(queries) == 2
            assert len(queries[0]["layers"]) == 6 and queries[1]["layers"] == []
            assert sum(item["tool_name"] == "get_layer_list" for item in data["tool_results"]) == 1


def test_decomposition_is_bounded_and_cannot_fabricate_a_missing_base_query():
    plans = [{"operations": ["query_layers"]}, {"questions": ["그중 tif는 몇 개야?"]}, CASES[1][1],
             {"operations": ["query_layers"]}, {"questions": ["조회"] * 4}]
    with client_for(plans) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            question = "레이어 목록과 그중 tif 개수 알려줘"
            result = client.post("/api/v1/agent/chat", json=body(question)).json()
            assert result["warning"] == "previous_result_unavailable"
            assert result["tool_results"] == []
            assert client.post("/api/v1/agent/chat", json=body(question)).status_code == 502
            assert not client.app.state.agent.busy
