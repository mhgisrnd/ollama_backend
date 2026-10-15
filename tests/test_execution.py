from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.main import create_app

BASE = "/api/v1/clients/pc-a"
SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def register(client):
    client.put(BASE, json={"display_name": "PC A", "app_version": "1"}).raise_for_status()
    client.put(BASE + "/tools", json={"tools": [{
        "name": "get_layer_list", "description": "List layers", "source": "python", "input_schema": SCHEMA,
    }]}).raise_for_status()


def call(client, **kwargs):
    return client.post(BASE + "/tools/call", json={"tool_name": "get_layer_list", "arguments": {}, **kwargs})


def test_roundtrip_heartbeat_and_duplicate_connection():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            assert ws.receive_json()["protocol_version"] == 1
            ws.send_json({"type": "heartbeat"})
            assert ws.receive_json() == {"type": "heartbeat_ack"}
            assert client.get("/api/v1/connections").json()[0]["client_id"] == "pc-a"
            with pytest.raises(WebSocketDisconnect) as duplicate:
                with client.websocket_connect(BASE + "/ws") as other:
                    other.receive_json()
            assert duplicate.value.code == 4409
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(call, client)
                request = ws.receive_json()
                assert request["type"] == "tool_call"
                assert call(client).status_code == 409
                # A wrong call ID must not complete the pending request.
                ws.send_json({"type": "tool_result", "call_id": "wrong", "status": "succeeded", "result": {}})
                ws.send_json({"type": "tool_result", "call_id": request["call_id"], "status": "succeeded", "result": {"layers": []}})
                response = pending.result(timeout=5)
                assert response.status_code == 200
                assert response.json()["result"] == {"layers": []}


def test_offline_and_input_validation():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        register(client)
        assert call(client).json()["detail"]["code"] == "client_offline"
        assert call(client, arguments={"unexpected": True}).status_code == 422
        assert call(client, tool_name="execute_script").status_code == 404


def test_timeout_then_late_result_does_not_complete_next_call():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        register(client)
        with client.websocket_connect(BASE + "/ws") as ws:
            ws.receive_json()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(call, client, timeout_seconds=1)
                first = ws.receive_json()
                assert pending.result(timeout=3).status_code == 504
                ws.send_json({"type": "tool_result", "call_id": first["call_id"], "status": "succeeded", "result": {}})
                pending = pool.submit(call, client)
                second = ws.receive_json()
                assert second["call_id"] != first["call_id"]
                ws.send_json({"type": "tool_result", "call_id": second["call_id"], "status": "failed", "error": "executor_busy"})
                assert pending.result(timeout=3).json()["status"] == "failed"


def test_disconnect_resolves_pending_as_unknown():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        register(client)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with client.websocket_connect(BASE + "/ws") as ws:
                ws.receive_json()
                pending = pool.submit(call, client)
                ws.receive_json()
                ws.close()
                response = pending.result(timeout=3)
                assert response.status_code == 503
                assert response.json()["detail"]["code"] == "client_disconnected"


def test_unregistered_socket_rejected():
    with TestClient(create_app(Settings(_env_file=None))) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(BASE + "/ws"):
                pass
