import json
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from test_agent import BASE, register
from test_query_engine import ROWS, TIFF, query


def client_for(plans, reviews=None):
    values = iter(plans)
    review_values = iter(reviews) if reviews is not None else None
    def handler(request):
        assert "format" in json.loads(request.content)
        if "decision" in json.loads(request.content)["format"].get("properties", {}):
            value = next(review_values) if review_values else {"decision": "accept", "reason": ""}
        else:
            value = next(values)
        return httpx.Response(200, json={"model": "test", "done": True,
            "message": {"role": "assistant", "content": json.dumps(value)}})
    return TestClient(create_app(Settings(_env_file=None, agent_mode="general", ollama_model="test"),
                                 transport=httpx.MockTransport(handler)))


def enable_metadata(client):
    register(client)
    tools = client.get(BASE + "/tools").json()["tools"]
    tools.append({"name": "get_layer_metadata", "source": "python", "description": "File metadata",
                  "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}})
    client.put(BASE + "/tools", json={"tools": tools}).raise_for_status()


def tasks(*requests):
    return {"tasks": [{"tool": "query_layers", "request": text} for text in requests]}


def request(text):
    return {"client_id": "pc-a", "session_id": "conversation", "messages": [{"role": "user", "content": text}]}


def reply(ws, name, rows=ROWS):
    call = ws.receive_json()
    assert call["tool_name"] == name
    ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded",
                  "result": {"count": len(rows), "layers": rows}})


def test_largest_file_and_followup_sum_are_generic_operations():
    largest = query(where=[TIFF], select=["name", "size_bytes"], order_by=[{"field": "size_bytes", "direction": "desc"}], limit=1)
    total = query(source="previous_result", aggregate={"function": "sum", "field": "size_bytes"})
    with client_for([tasks("largest TIFF"), largest.model_dump(), tasks("sum previous result"), total.model_dump()]) as client:
        enable_metadata(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("largest TIFF"))
            reply(ws, "get_layer_metadata")
            result = pending.result(timeout=5).json()
            assert result["query_result"]["records"] == [{"name": "large.TIFF", "size_bytes": 900}]
            followup = client.post("/api/v1/agent/chat", json=request("sum previous result")).json()
            assert followup["completion_status"] == "completed"
            assert followup["query_result"]["records"][0]["value"] == 900


def test_unavailable_fields_and_old_clients_refuse_without_execution():
    for field in ("resolution", "size_bytes"):
        with client_for([tasks("query"), query(select=[field]).model_dump()]) as client:
            register(client)  # Old client does not advertise file metadata.
            with client.websocket_connect(BASE + "/ws") as ws:
                ws.receive_json()
                result = client.post("/api/v1/agent/chat", json=request("query")).json()
                assert result["warning"] == "query_not_executed"
                assert result["query_result"] is None and result["tool_results"] == []


def test_list_with_missing_file_information_still_returns_all_layers():
    rows = [dict(row) for row in ROWS] + [{"name": "temporary", "kind": "vector", "visible": True}]
    with client_for([tasks("list"), query(select=["name", "path", "size_bytes"]).model_dump()]) as client:
        enable_metadata(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("list"))
            reply(ws, "get_layer_metadata", rows)
            result = pending.result(timeout=5).json()
            assert result["completion_status"] == "completed"
            assert len(result["query_result"]["records"]) == 5
            assert result["query_result"]["records"][-1]["size_bytes"] is None
            assert "확인 불가" in result["message"]["content"]
            assert "None" not in result["message"]["content"]


def test_missing_values_cannot_be_reported_as_a_global_maximum():
    rows = [dict(row) for row in ROWS]
    rows[0]["size_bytes"] = None
    largest = query(select=["name", "size_bytes"], order_by=[{"field": "size_bytes", "direction": "desc"}], limit=1)
    followup = query(source="previous_result", aggregate={"function": "sum", "field": "size_bytes"})
    with client_for([tasks("largest"), largest.model_dump(), tasks("sum previous"), followup.model_dump()]) as client:
        enable_metadata(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("largest"))
            reply(ws, "get_layer_metadata", rows)
            result = pending.result(timeout=5).json()
            assert result["completion_status"] == "partial"
            assert result["warning"] == "incomplete_data"
            assert result["query_result"]["records"][0]["name"] == "boundary.shp"
            assert "전체 대상" in result["message"]["content"]
            result = client.post("/api/v1/agent/chat", json=request("sum previous")).json()
            assert result["completion_status"] == "partial"
            assert result["query_result"]["records"][0]["value"] == 2000
            assert "전체 대상" in result["message"]["content"]


def test_compound_query_lazily_enriches_previous_snapshot():
    largest = query(source="previous_result", select=["name", "size_bytes"], order_by=[{"field": "size_bytes", "direction": "desc"}], limit=1)
    with client_for([tasks("list", "largest previous"), query(where=[TIFF]).model_dump(), largest.model_dump()]) as client:
        enable_metadata(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("list and largest"))
            reply(ws, "get_layer_list", [{key: value for key, value in row.items() if key not in {"size_bytes", "modified_at"}} for row in ROWS])
            reply(ws, "get_layer_metadata")
            data = pending.result(timeout=5).json()
            assert data["completion_status"] == "completed"
            assert data["query_result"]["records"] == [{"name": "large.TIFF", "size_bytes": 900}]


def test_unsupported_task_stops_entire_plan_and_missing_previous_is_not_faked():
    with client_for([{"tasks": [{"tool": "unsupported", "request": "delete"}]},
                     tasks("previous"), query(source="previous_result").model_dump()]) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            result = client.post("/api/v1/agent/chat", json=request("delete")).json()
            assert result["warning"] == "clarification_required" and not result["tool_results"]
            result = client.post("/api/v1/agent/chat", json=request("previous")).json()
            assert result["warning"] == "query_not_executed" and not result["tool_results"]


def test_semantic_review_can_reject_a_valid_but_unrelated_plan_before_execution():
    with client_for([tasks("highest resolution"), query(select=["name", "size_bytes"]).model_dump()],
                    reviews=[{"decision": "unsupported", "reason": "해상도 정보가 제공되지 않습니다."}]) as client:
        enable_metadata(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            result = client.post("/api/v1/agent/chat", json=request("highest resolution")).json()
            assert result["query_result"] is None and result["tool_results"] == []
            assert "해상도" in result["message"]["content"]
