from pydantic import ConfigDict, Field
from typing import Literal

from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.registry import ClientId
from app.schemas.execution import ToolResult


class AgentChatRequest(ChatRequest):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "client_id": "연결 목록의 client_id", "messages": [{"role": "user", "content": "현재 레이어 목록을 알려줘"}],
    }})
    client_id: ClientId
    session_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    reference_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$", description="reference_id from the last displayed numbered query_result; required for opening files by number")
    request_token: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$", description="Client-generated token for cancelling this request")


class AgentToolResult(ToolResult):
    tool_name: str


class AgentChatResponse(ChatResponse):
    client_id: str
    tool_results: list[AgentToolResult] = Field(default_factory=list)
    warning: str | None = None
    requested_tools: list[str] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    completion_status: Literal["completed", "partial", "failed", "unverified"] = "unverified"
    session_id: str | None = None
    query_result: dict | None = None
