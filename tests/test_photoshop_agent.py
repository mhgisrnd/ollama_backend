from concurrent.futures import ThreadPoolExecutor

from test_agent import BASE
from test_general_agent import client_for, enable_metadata, tasks, request, reply
from test_query_engine import query, ROWS


def numbered(*numbers):
    return {"tasks": [{"tool": "open_numbered_images", "request": "Open numbered files", "numbers": list(numbers)}]}


def enable_photoshop(client):
    enable_metadata(client)
    tools = client.get(BASE + "/tools").json()["tools"]
    for name in ("photoshop_list_documents", "photoshop_get_document_info", "photoshop_get_layers", "photoshop_open_images"):
        tools.append({"name": name, "source": "photoshop_mcp", "description": name,
                      "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}})
    client.put(BASE + "/tools", json={"tools": tools}).raise_for_status()


def opening(count=1):
    return {"tasks": [{"tool": "photoshop_open_images", "request": "Open requested images in Photoshop", "requested_count": count}]}


def test_repeat_requests_create_distinct_calls_using_real_snapshot_paths():
    plan = query(select=["name", "path"], limit=1).model_dump()
    with client_for([opening(), plan, opening(), plan]) as client:
        enable_photoshop(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            ids = []
            for number in (1, 2):
                pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("Open first image"))
                reply(ws, "get_layer_list")
                call = ws.receive_json()
                ids.append(call["call_id"])
                assert call["tool_name"] == "photoshop_open_images"
                assert call["arguments"] == {"paths": ["small.tif"]}
                ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded",
                              "result": {"documents": [{"id": number, "name": f"work-{number}"}], "failures": []}})
                result = pending.result(timeout=5).json()
                assert result["completion_status"] == "completed"
                assert "새 포토샵 작업 탭 1개" in result["message"]["content"]
            assert ids[0] != ids[1]


def test_oversized_batch_is_refused_before_opening_any_document():
    rows = [{"name": f"image-{i}.png", "path": f"image-{i}.png", "kind": "raster"} for i in range(6)]
    with client_for([opening(None), query(select=["name", "path"]).model_dump()]) as client:
        enable_photoshop(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("Open images"))
            reply(ws, "get_layer_list", rows)
            result = pending.result(timeout=5).json()
            assert result["completion_status"] == "failed"
            assert "최대 5개" in result["message"]["content"]
            assert all(tool["tool_name"] != "photoshop_open_images" for tool in result["tool_results"])


def test_partial_open_is_not_reported_as_complete_and_is_not_retried():
    with client_for([opening(2), query(select=["name", "path"], limit=2).model_dump()]) as client:
        enable_photoshop(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("Open two images"))
            reply(ws, "get_layer_list")
            call = ws.receive_json()
            ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded",
                          "result": {"documents": [{"id": 1, "name": "work"}], "failures": [{"source": "large.TIFF", "message": "cannot open"}]}})
            result = pending.result(timeout=5).json()
            assert result["completion_status"] == "partial"
            assert result["warning"] == "photoshop_open_partial"
            assert "1개 파일은 열지 못했습니다" in result["message"]["content"]


def test_all_images_cannot_be_silently_clamped_to_five_by_planner():
    rows = [{"name": f"image-{i}.tif", "path": f"image-{i}.tif", "kind": "raster"} for i in range(12)]
    with client_for([opening(None), query(select=["name", "path"], limit=5).model_dump()]) as client:
        enable_photoshop(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("Open all TIFFs"))
            reply(ws, "get_layer_list", rows)
            result = pending.result(timeout=5).json()
            assert result["completion_status"] == "failed"
            assert "12개" in result["message"]["content"] and "이번에는 열지 않았습니다" in result["message"]["content"]
            assert [tool["tool_name"] for tool in result["tool_results"]] == ["get_layer_list", "query_layers"]


def test_numbered_open_uses_the_displayed_batch_list_even_after_another_open():
    rows = [{"name": f"image-{i}.tif", "path": f"image-{i}.tif", "kind": "raster"} for i in range(12)]
    plans = [opening(None), query(select=["name", "path"], limit=5).model_dump(), numbered(1, 2, 4, 5, 6), numbered(6)]
    with client_for(plans) as client:
        enable_photoshop(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("Open all TIFFs"))
            reply(ws, "get_layer_list", rows)
            first = pending.result(timeout=5).json()
            assert len(first["query_result"]["records"]) == 12
            assert first["query_result"]["records"][5]["number"] == 6
            assert first["query_result"]["records"][5]["name"] == "image-5.tif"
            for numbers in ([1, 2, 4, 5, 6], [6]):
                pending = pool.submit(client.post, "/api/v1/agent/chat", json={**request("Open numbered files"), "reference_id": first["query_result"]["reference_id"]})
                call = ws.receive_json()
                assert call["tool_name"] == "photoshop_open_images"
                assert call["arguments"]["paths"] == [rows[number-1]["path"] for number in numbers]
                ws.send_json({"type": "tool_result", "call_id": call["call_id"], "status": "succeeded", "result": {
                    "documents": [{"id": i, "name": path} for i, path in enumerate(call["arguments"]["paths"])], "failures": []}})
                assert pending.result(timeout=5).json()["completion_status"] == "completed"


def test_numbered_open_without_a_list_or_with_invalid_or_nonimage_numbers_never_opens():
    plans = [numbered(1), tasks("list"), query().model_dump(), numbered(2, 4), numbered(1, 99), numbered(1, 2, 3, 4, 5, 6)]
    with client_for(plans) as client:
        enable_photoshop(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            result = client.post("/api/v1/agent/chat", json=request("Open 1")).json()
            assert "먼저 레이어 목록" in result["message"]["content"] and not result["tool_results"]
            pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("list"))
            reply(ws, "get_layer_list")
            listing = pending.result(timeout=5).json()
            assert listing["completion_status"] == "completed"
            for text in ("Open vector number", "Open missing number", "Open six numbers"):
                result = client.post("/api/v1/agent/chat", json={**request(text), "reference_id": listing["query_result"]["reference_id"]}).json()
                assert result["completion_status"] == "failed" and not result["tool_results"]


def test_an_unseen_new_list_cannot_retarget_an_old_displayed_number():
    with client_for([tasks("list"), query().model_dump(), tasks("new list"), query().model_dump(), numbered(1)]) as client:
        enable_photoshop(client)
        with client.websocket_connect(BASE + "/ws") as ws, ThreadPoolExecutor(1) as pool:
            ws.receive_json()
            references = []
            for rows in (ROWS, list(reversed(ROWS))):
                pending = pool.submit(client.post, "/api/v1/agent/chat", json=request("list"))
                reply(ws, "get_layer_list", rows)
                references.append(pending.result(timeout=5).json()["query_result"]["reference_id"])
            assert references[0] != references[1]
            result = client.post("/api/v1/agent/chat", json={**request("Open 1"), "reference_id": references[0]}).json()
            assert result["completion_status"] == "failed" and not result["tool_results"]
            assert "조회 목록이 바뀌었거나" in result["message"]["content"]
