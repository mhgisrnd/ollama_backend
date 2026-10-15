import json
from datetime import datetime
from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ClientId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")]


class ClientRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={
        "example": {"display_name": "개발 PC 벡터 프로그램", "app_version": "1.0.0"},
    })
    display_name: str = Field(min_length=1, max_length=120)
    app_version: str = Field(min_length=1, max_length=64)


class ClientRecord(ClientRegistration):
    client_id: str
    registered_at: datetime
    updated_at: datetime


class RegisteredTool(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z_][a-zA-Z0-9_-]*$")
    description: str = Field(min_length=1, max_length=2000)
    source: Literal["photoshop_mcp", "python"]
    input_schema: dict[str, Any]

    @field_validator("input_schema")
    @classmethod
    def validate_input_schema(cls, schema):
        if len(json.dumps(schema, ensure_ascii=False).encode("utf-8")) > 65536:
            raise ValueError("input_schema는 64KiB 이하여야 합니다.")
        if schema.get("type") != "object":
            raise ValueError("input_schema의 최상위 type은 object여야 합니다.")
        # A self-contained schema keeps registration independent of external resources.
        stack = [(schema, 0)]
        while stack:
            node, depth = stack.pop()
            if depth > 32:
                raise ValueError("input_schema의 중첩 깊이는 32 이하여야 합니다.")
            if isinstance(node, dict):
                if any(key in node for key in ("$ref", "$dynamicRef", "$recursiveRef")):
                    raise ValueError("현재 단계에서는 참조 없는 인라인 JSON Schema만 지원합니다.")
                stack.extend((value, depth + 1) for value in node.values())
            elif isinstance(node, list):
                stack.extend((value, depth + 1) for value in node)
        if schema.get("$schema", "https://json-schema.org/draft/2020-12/schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError("JSON Schema Draft 2020-12만 지원합니다. $schema는 생략할 수 있습니다.")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValueError(f"올바르지 않은 JSON Schema: {exc.message}") from exc
        properties = schema.get("properties", {})
        if not set(schema.get("required", [])).issubset(properties):
            raise ValueError("required 항목은 properties에 정의되어야 합니다.")
        return schema


TOOL_EXAMPLE = {
    "tools": [{
        "name": "photoshop_ping", "description": "Photoshop 연결 상태를 확인합니다.",
        "source": "photoshop_mcp",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    }],
}


class ToolRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": TOOL_EXAMPLE})
    tools: list[RegisteredTool] = Field(max_length=128)

    @model_validator(mode="after")
    def unique_names(self):
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("한 클라이언트의 도구 이름은 중복될 수 없습니다.")
        return self


class ToolCatalog(ToolRegistration):
    client_id: str
    revision: int
    updated_at: datetime | None
