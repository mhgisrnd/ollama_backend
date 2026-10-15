import asyncio
import json

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.execution.connections import ExecutionError
from app.schemas.execution import ToolCallRequest, ToolResult
from app.schemas.registry import ClientId
from app.storage.registry import ClientNotFound

router = APIRouter(prefix="/api/v1", tags=["tool execution"])


@router.get("/connections", summary="현재 WebSocket 연결 목록")
async def connections(request: Request):
    return [{"client_id": key, "connection_id": value.connection_id, "pending_calls": len(value.pending)}
            for key, value in request.app.state.connections.connections.items()]


@router.post("/clients/{client_id}/tools/call", response_model=ToolResult, summary="지정 도구 실행 테스트 (LLM 없음)")
async def call_tool(client_id: ClientId, body: ToolCallRequest, request: Request):
    """연결된 PC에서 도구를 실행하고 결과를 기다립니다. 타임아웃·연결 끊김 시 자동 재전송하지 않습니다."""
    catalog = await asyncio.to_thread(request.app.state.registry.get_tools, client_id)
    tool = next((item for item in catalog.tools if item.name == body.tool_name), None)
    if tool is None:
        raise ExecutionError(404, "tool_not_registered", "해당 프로그램에 등록되지 않은 도구입니다.")
    if len(json.dumps(body.arguments).encode()) > 65536:
        raise ExecutionError(422, "invalid_arguments", "도구 인자가 너무 큽니다.")
    if not Draft202012Validator(tool.input_schema).is_valid(body.arguments):
        raise ExecutionError(422, "invalid_arguments", "도구 인자가 등록된 입력 스키마와 일치하지 않습니다.")
    return await request.app.state.connections.call(client_id, body)


@router.websocket("/clients/{client_id}/ws")
async def client_socket(websocket: WebSocket, client_id: ClientId):
    manager = websocket.app.state.connections
    try:
        await asyncio.to_thread(websocket.app.state.registry.get_tools, client_id)
    except ClientNotFound:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    try:
        connection = manager.attach(client_id, websocket)
    except ExecutionError:
        await websocket.close(code=4409)
        return
    try:
        await connection.send({"type": "ready", "protocol_version": 1, "connection_id": connection.connection_id})
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=45)
            if len(raw.encode("utf-8")) > 1024 * 1024:
                await websocket.close(code=1009)
                break
            message = json.loads(raw)
            if isinstance(message, dict) and message.get("type") == "heartbeat":
                await connection.send({"type": "heartbeat_ack"})
            else:
                manager.resolve(connection, ToolResult.model_validate(message))
    except (WebSocketDisconnect, TimeoutError):
        pass
    except (ValueError, ValidationError):
        await websocket.close(code=1008)
    finally:
        manager.detach(client_id, connection)
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
