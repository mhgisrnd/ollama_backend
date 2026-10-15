import asyncio
import time
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import WebSocket

from app.schemas.execution import ToolCallRequest, ToolResult


class ExecutionError(Exception):
    def __init__(self, status, code, message, call_id=None):
        self.status, self.code, self.message, self.call_id = status, code, message, call_id


@dataclass
class Connection:
    websocket: WebSocket
    connection_id: str = field(default_factory=lambda: uuid4().hex)
    pending: dict = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, message):
        async with self.send_lock:
            await asyncio.wait_for(self.websocket.send_json(message), timeout=5)


class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, Connection] = {}

    def attach(self, client_id, websocket):
        if client_id in self.connections:
            raise ExecutionError(409, "client_already_connected", "같은 ID의 프로그램이 이미 연결되어 있습니다.")
        connection = Connection(websocket)
        self.connections[client_id] = connection
        return connection

    def detach(self, client_id, connection):
        if self.connections.get(client_id) is connection:
            del self.connections[client_id]
        for call_id, future in list(connection.pending.items()):
            if not future.done():
                future.set_exception(ExecutionError(503, "client_disconnected", "연결이 끊겼습니다. 실행 결과는 확인되지 않았으며 자동 재실행하지 않습니다.", call_id))

    def resolve(self, connection, result: ToolResult):
        future = connection.pending.get(result.call_id)
        # Late, duplicate and unrelated results cannot complete another call.
        if future is not None and not future.done():
            future.set_result(result)

    async def call(self, client_id, body: ToolCallRequest):
        connection = self.connections.get(client_id)
        if connection is None:
            raise ExecutionError(503, "client_offline", "해당 벡터 프로그램이 연결되어 있지 않습니다.")
        if connection.pending:
            raise ExecutionError(409, "client_busy", "해당 프로그램의 이전 요청이 아직 대기 중입니다.")
        call_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        connection.pending[call_id] = future
        try:
            async with asyncio.timeout(body.timeout_seconds):
                await connection.send({
                    "type": "tool_call", "call_id": call_id, "tool_name": body.tool_name,
                    "arguments": body.arguments, "expires_at": time.time() + body.timeout_seconds,
                })
                return await future
        except TimeoutError as exc:
            raise ExecutionError(504, "execution_timeout", "결과 대기 시간이 초과되었습니다. 실행이 계속될 수 있으며 자동 재실행하지 않습니다.", call_id) from exc
        except ExecutionError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ExecutionError(503, "delivery_failed", "요청 전달 결과가 불명확합니다. 자동 재실행하지 않습니다.", call_id) from exc
        finally:
            connection.pending.pop(call_id, None)
            if not future.done():
                future.cancel()
