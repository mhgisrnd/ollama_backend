import json
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from test_agent import BASE, register
from test_query_engine import ROWS, TIFF, query


def client_for(plans, reviews=None, captured=None):
    values = iter(plans)
    review_values = iter(reviews) if reviews is not None else None
    def handler(request):
        if captured is not None:
            captured.append(json.loads(request.content))
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


def test_shorthand_format_counts_share_snapshot_and_keep_independent_scopes():
    captured = []
    count = {"function": "count", "field": "*"}
    tif = query(where=[TIFF], select=["value"], aggregate=count)
    shp = query(where=[{"field": "extension", "operator": "in", "values": [".shp"]}],
                select=["value"], aggregate=count)
    with client_for([tasks("현재 TIFF 개수", "현재 SHP 개수"), tif.model_dump(), shp.model_dump()], captured=captured) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("tif와 shp 개수가 궁금해"))
            reply(ws, "get_layer_list")
            result = pending.result(timeout=5).json()
            assert result["completion_status"] == "completed"
            queries = [item for item in result["tool_results"] if item["tool_name"] == "query_layers"]
            assert [item["result"]["records"][0]["value"] for item in queries] == [3, 1]
            assert sum(item["tool_name"] == "get_layer_list" for item in result["tool_results"]) == 1
            assert "각각" in captured[0]["messages"][-1]["content"]


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
            assert result["query_result"]["records"] == [{"number": 1, "name": "large.TIFF", "size_bytes": 900}]
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
            assert "전체 결과와 다를 수 있습니다" in result["message"]["content"]
            result = client.post("/api/v1/agent/chat", json=request("sum previous")).json()
            assert result["completion_status"] == "partial"
            assert result["query_result"]["records"][0]["value"] == 2000
            assert "전체 결과와 다를 수 있습니다" in result["message"]["content"]


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
            assert data["query_result"]["records"] == [{"number": 1, "name": "large.TIFF", "size_bytes": 900}]


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
            assert "조회 방법을 확정하지 못했습니다" in result["message"]["content"]


def test_invalid_aggregate_sort_is_repaired_with_rejected_candidate_and_error():
    invalid = query(select=["name", "size_bytes"], aggregate={"function": "max", "field": "size_bytes"},
                    order_by=[{"field": "size_bytes", "direction": "desc"}], limit=1).model_dump()
    correct = query(select=["name", "size_bytes"], order_by=[{"field": "size_bytes", "direction": "desc"}], limit=1).model_dump()
    captured = []
    with client_for([tasks("largest file"), invalid, correct], captured=captured) as client:
        enable_metadata(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("largest file"))
            reply(ws, "get_layer_metadata")
            result = pending.result(timeout=5).json()
            assert result["completion_status"] == "completed"
            assert result["query_result"]["records"] == [{"number": 1, "name": "boundary.shp", "size_bytes": 2000}]
    repair = captured[3]["messages"]
    feedback = next(json.loads(message["content"]) for message in repair if '"rejected_query"' in message["content"])
    assert feedback["rejected_query"] == invalid
    assert "group/value" in feedback["validation_error"]


def test_exhausted_repair_keeps_diagnostics_in_logs_only(caplog):
    candidate = query().model_dump()
    diagnostic = "집계 후 정렬은 group/value, size_bytes 규칙을 적용하세요."
    with client_for([tasks("query"), candidate, candidate], reviews=[
            {"decision": "repair", "reason": diagnostic}, {"decision": "repair", "reason": diagnostic}]) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            result = client.post("/api/v1/agent/chat", json=request("query")).json()
    assert result["completion_status"] == "failed" and not result["tool_results"]
    assert "group/value" not in result["message"]["content"]
    assert diagnostic in caplog.text


def test_group_output_aliases_are_valid_plan_fields():
    grouped = query(select=["group", "value"], group_by="kind", aggregate={"function": "count", "field": "*"},
                    order_by=[{"field": "value", "direction": "desc"}]).model_dump()
    with client_for([tasks("counts by kind"), grouped]) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("counts by kind"))
            reply(ws, "get_layer_list")
            result = pending.result(timeout=5).json()
            assert result["completion_status"] == "completed"
            assert result["query_result"]["records"] == [{"group": "raster", "value": 3}, {"group": "vector", "value": 1}]


def test_compound_layer_review_is_scoped_and_photoshop_is_a_separate_task():
    captured = []
    plan = {"tasks": [{"tool": "query_layers", "request": "현재 레이어 목록 확인"},
                      {"tool": "photoshop_ping", "request": "포토샵 연결 상태 확인"}]}
    with client_for([plan, query(select=["name", "extension", "kind", "visible"]).model_dump()], captured=captured) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("레이어 목록과 포토샵 연결상태 확인해줘"))
            reply(ws, "get_layer_list")
            call = ws.receive_json()
            assert call["tool_name"] == "photoshop_ping"
            ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded", "result": {"connected": True}})
            result = pending.result(timeout=5).json()
            assert result["completion_status"] == "completed" and not result["missing_tools"]
            assert "포토샵 통신에 성공" in result["message"]["content"]
            assert len(result["query_result"]["records"]) == 4
    review = next(value for value in captured if "decision" in value["format"].get("properties", {}))
    payload = json.loads(review["messages"][-1]["content"])
    assert payload["request"] == "현재 레이어 목록 확인"
    assert payload["original_request"] == "레이어 목록과 포토샵 연결상태 확인해줘"
    assert "photoshop_ping" in payload["available_tools"]
    assert payload["task_plan"][1]["tool"] == "photoshop_ping"
