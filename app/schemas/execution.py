from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "tool_name": "get_layer_list", "arguments": {}, "timeout_seconds": 15,
    }})
    tool_name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=15, ge=1, le=60)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["tool_result"] = "tool_result"
    call_id: str = Field(min_length=1, max_length=64)
    status: Literal["succeeded", "failed"]
    result: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def valid_result(self):
        if self.status == "succeeded" and (self.result is None or self.error is not None):
            raise ValueError("Successful results require result and no error")
        if self.status == "failed" and not self.error:
            raise ValueError("Failed results require error")
        return self
