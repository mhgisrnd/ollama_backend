"""Validated read-only queries. No Qt, MCP or model dependencies."""
from pathlib import PurePosixPath
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    extensions: list[Literal[".tif", ".tiff", ".shp", ".dxf", ".ecw"]] = Field(max_length=5)
    visible: bool | None


class LayerQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: Literal["current", "previous_result"]
    filters: Filters
    output: Literal["count", "list"]


def inline_schema():
    # Self-contained schema, also compatible with the current tool registry.
    schema = LayerQuery.model_json_schema()
    definitions = schema.pop("$defs")
    schema["properties"]["filters"] = definitions["Filters"]
    return schema


TOOL = {"type": "function", "function": {
    "name": "query_layers",
    "description": "레이어를 조건별로 조회합니다. 개수 계산도 이 도구가 수행합니다. current는 최신 전체 레이어, previous_result는 직전 조회 결과입니다. extensions=[]는 모든 확장자, visible=null은 표시 여부 전체입니다. 이전 결과에 없는 종류로 조건을 바꾸려면 current를 사용하세요.",
    "parameters": inline_schema(),
}}


class QuerySession:
    """One isolated session. Count output still retains rows for follow-up queries."""
    def __init__(self):
        self.previous_rows = None
        self.last_query = None
        self.result_id = None

    def context(self):
        return {"previous_result_available": self.previous_rows is not None,
                "previous_result_id": self.result_id,
                "previous_count": len(self.previous_rows) if self.previous_rows is not None else None,
                "previous_query": self.last_query.model_dump() if self.last_query else None}

    def execute(self, query: LayerQuery, current_provider):
        if query.source == "previous_result":
            if self.previous_rows is None:
                raise ValueError("No previous result in this session")
            rows = self.previous_rows
        else:
            rows = current_provider()
        selected = []
        for row in rows:
            extension = PurePosixPath(str(row.get("path") or row.get("name") or "").replace("\\", "/")).suffix.lower()
            if query.filters.extensions and extension not in query.filters.extensions:
                continue
            if query.filters.visible is not None and row.get("visible") is not query.filters.visible:
                continue
            selected.append(dict(row))
        self.previous_rows = selected
        self.last_query = query
        self.result_id = uuid4().hex
        return {"result_id": self.result_id, "count": len(selected), "source": query.source,
                "names": [row.get("name", "") for row in selected] if query.output == "list" else []}
