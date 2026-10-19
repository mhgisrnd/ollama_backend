"""Capability-driven agent. No question keyword rules or arbitrary code execution."""
import asyncio
import copy
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.query_engine import BASE_FIELDS, FIELDS, FILE_FIELDS, FIELD_LABELS, Query, QueryError, execute, schema, validate_query, select_positions
from app.execution.connections import ExecutionError
from app.llm.ollama import OllamaError
from app.schemas.agent import AgentChatResponse, AgentToolResult
from app.schemas.chat import ChatMessage
from app.schemas.execution import ToolCallRequest
from app.agent.formatting import format_size
from app.agent.count_request import expand_count_request
from app.agent.photoshop import READ_TOOLS, OPEN_TOOL, IMAGE_EXTENSIONS, describe

log = logging.getLogger("uvicorn.error.agent.general")


class PlanningError(QueryError):
    """Internal planning diagnostics must stay in server logs."""


class TargetError(QueryError):
    """Locally written actionable messages, safe to display."""


def planning_examples():
    # Operation examples, not question matching or execution overrides.
    common = {"source": "current", "where": [], "select": ["name", "size_bytes"],
              "order_by": [], "offset": 0, "limit": 1000, "aggregate": None, "group_by": None}
    return json.dumps([
        {"intent": "inspect or explain the current layer list without extra criteria",
         "query": {**common, "select": ["name", "extension", "kind", "visible"]}},
        {"intent": "return the row with greatest numeric field, including its identity",
         "query": {**common, "order_by": [{"field": "size_bytes", "direction": "desc"}], "limit": 1}},
        {"intent": "return only the second row in descending numeric order, not the first two rows",
         "query": {**common, "order_by": [{"field": "size_bytes", "direction": "desc"}], "offset": 1, "limit": 1}},
        {"intent": "return only the maximum numeric value, without row identity",
         "query": {**common, "select": ["value"], "aggregate": {"function": "max", "field": "size_bytes"}}},
        {"intent": "count records per extension",
         "query": {**common, "select": ["group", "value"], "group_by": "extension",
                   "aggregate": {"function": "count", "field": "*"}}},
        {"intent": "count all matching records as a single number",
         "query": {**common, "select": ["value"], "aggregate": {"function": "count", "field": "*"}}},
        {"intent": "sum the numeric field of all matching records as a single number",
         "query": {**common, "select": ["value"], "aggregate": {"function": "sum", "field": "size_bytes"}}},
    ])


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool: Literal["query_layers", "photoshop_ping", "photoshop_list_documents", "photoshop_get_document_info", "photoshop_get_layers", "photoshop_open_images", "open_numbered_images", "unsupported", "clarify"]
    request: str = Field(min_length=1, max_length=4000)
    requested_count: int | None = Field(default=None, ge=1, le=1000,
                                        description="Explicit number of images requested; null for all/unspecified. An ordinal single image is 1. Never substitute an execution batch limit.")
    numbers: list[int] = Field(default_factory=list, max_length=1000,
                                                           description="1-based row numbers from the last displayed layer list; preserve all explicitly requested numbers")


class Tasks(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tasks: list[Task] = Field(min_length=1, max_length=3)


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["accept", "repair", "unsupported", "clarify"]
    reason: str = Field(max_length=1000)


@dataclass
class Session:
    connection_id: str
    rows: list | None = None
    last_query: dict | None = None
    limitations: list = field(default_factory=list)
    numbered_rows: list | None = None
    reference_id: str | None = None
    touched: float = field(default_factory=time.monotonic)


ROUTE = """You plan desktop work using ONLY the advertised tools. Return ordered tasks, never answers.
query_layers: inspect layer metadata, filters, sorting, top-N, counts, numeric aggregates and grouping.
This includes requests to describe, explain, summarize, or show the current layer list. An overview is a supported inspection, not an ambiguous request.
For broad inspection use the current project and basic metadata; no filter or additional criterion is required.
photoshop_ping: check Photoshop communication, not document editing.
photoshop_list_documents: list documents open in Photoshop.
photoshop_get_document_info: inspect active Photoshop document name and dimensions.
photoshop_get_layers: inspect layers INSIDE the active Photoshop document, not the vector application's layer list.
photoshop_open_images: explicitly requested opening of image layers from the current project or previous query result in NEW Photoshop working tabs. One task includes selecting the image targets; do not split target selection into another query_layers task.
open_numbered_images: open explicitly referenced ROW NUMBERS from the most recently displayed layer list. Set numbers to every requested index (e.g. [1,2,4,5,6]); one task handles all numbers. This uses photoshop_open_images internally.
When a user refers to numbered files, including comma-separated non-contiguous indices, use open_numbered_images, NOT a relational query or separate per-file tasks. Extract the indices even when no numbered list is available; the executor will explain what is missing. Ranking by size/name is different: use photoshop_open_images for those requests.
For tasks other than open_numbered_images set numbers=[]. Never convert reference indices to a count or truncate them to a batch limit.
Preserve invalid numbers such as 0 or out-of-range indices exactly; the executor rejects them. Never replace them with valid nearby numbers.
For opening extract requested_count from the user's intent: null for all or unspecified count, N for explicitly N images, 1 for an ordinal single image. Never replace all with a batch limit. For other tasks requested_count=null.
Only opening working copies is supported; editing, deleting and saving documents are unsupported.
unsupported: requested ability does not exist (editing, deletion, synthesis, etc).
clarify: target or intent cannot be determined from the current question and session.
Split independently requested outputs into tasks (at most 3), preserving their dependencies and constraints.
Default to EXACTLY ONE task. Do not fill the task list to its maximum size.
A tool includes its own data fetching and execution steps. Never add extra tasks for fetching metadata, validating paths, formatting, or opening prerequisites.
Only split when the user explicitly requests distinct outputs, such as a layer list AND Photoshop connection state.
A single list overview is one query_layers task, not separate name/size/path tasks.
A row's name and size are columns of ONE task, not separate tasks. A single ranking question needs one query_layers task.
Do not replace unsupported requests with a similar supported operation. Do not answer a size/ranking request with a count.
Task request must preserve the meaning of the original Korean request. Prefer the user's original wording.
No task is executed until its tool and arguments pass validation."""

PLAN = """Translate the layer question into a read-only relational query, not an answer.
source=current reads current layer metadata; previous_result filters the last returned result.
where predicates are ANDed. Values are strings, including 'true'/'false' for booleans and units for sizes.
eq/in accept one or more alternatives, ne excludes all listed alternatives. Range/contains take one value.
TIFF includes .tif and .tiff: use extension in [".tif",".tiff"]. No extension restriction means where=[].
select lists fields to display. order_by sorts (asc/desc); limit controls returned row count.
offset skips rows AFTER filtering and sorting, then limit takes rows. Default offset=0.
Ordinal Nth means offset=N-1, limit=1. Top N means offset=0, limit=N. Starting at position N for K items means offset=N-1, limit=K.
Ordinal positions refer to sorted rows, not distinct numeric values; equal values retain their original order.
For largest/smallest FILE, return the name and size_bytes, sort size_bytes, limit=1, aggregate=null.
For count: aggregate={function:count,field:*}. For total/average numeric values use sum/avg.
Grouped aggregate rows have group/value columns; order_by can sort those columns.
For numeric min/max only (no file identity requested), aggregate=min/max. group_by groups aggregates, otherwise null.
An aggregate returns only group/value, never the original file identity. For row identity use sorting, not aggregation.
For aggregate queries select=["group","value"] if grouped, otherwise select=["value"].
Use group_by only when separate per-category results are explicitly requested. A filtered total count is not grouped.
Short questions such as 'tif와 shp 개수가 궁금해' request separate counts per format, not a combined total.
For separate TIFF and SHP counts prefer independent tasks: TIFF uses [.tif,.tiff] together, SHP uses [.shp]. Each reads current unless the user explicitly refers to previous results.
DXF and ECW use [.dxf] and [.ecw]. A count does not require size_bytes, modified_at, or Photoshop data.
For plain lists use aggregate=null, group_by=null. Never turn unknown fields into count or drop requested constraints.
Use only fields required by the request. For a plain list or overview select=["name","extension","kind","visible"], not size_bytes/modified_at/path.
Do not add sorting, file fields or filters unless required by the user's intent. Display-only missing values do not prevent listing a layer.
Field names are free strings so missing fields can be represented honestly: the server will reject unavailable fields.
If the user requests unavailable resolution, for example, reference resolution rather than pretending name/count answers it.
Use previous_result only when it exists or an earlier task in this request produces it; otherwise it remains unresolved.
Return exactly the query schema. Do not invent field values, paths, numeric results, code or SQL.""" + "\nOperation examples: " + planning_examples()

REVIEW = """Independently check whether a read-only query fulfills the user's original intent.
Do not execute, answer, or assume valid JSON means a correct plan.
Check the requested output (identity, ordering/top-N, count, total, average, grouping), fields,
all filters, units, and previous-result scope. Use only the declared available capabilities.
Check ordinal positions separately from counts: Nth one requires offset=N-1 and limit=1; top N requires offset=0 and limit=N.
Reject unnecessary file fields or ordering for a plain list; prefer the minimum information needed to fulfill the request.
Evaluate the current task within the whole task plan; another task may cover another requested output.
Your ONLY responsibility is the scoped layer subtask in request. The original_request is context, not additional work for this query.
Other tasks are executed separately. Never require a layer query to include Photoshop connectivity: photoshop_ping handles it.
Only judge layer fields against available_fields; judge other task capabilities against available_tools.
Never allow an unsupported concept in the original request to be replaced silently by a supported task.
If a requested concept needs unavailable information, choose unsupported; do not substitute another field.
If the query drops constraints or uses the wrong operation, choose repair and explain how to preserve the original request.
Follow the query-language definitions literally: eq/in with multiple values means alternatives, not AND.
The metadata contract treats TIFF/tif/tiff as one image family (.tif and .tiff). Do not remove either extension when reviewing that family.
Do not request a change when the candidate already performs the requested operation with the declared semantics.
Check every aspect before returning repair; report all necessary changes together, including projection and grouping, not only the first problem.
If the request is ambiguous choose clarify. Accept only a complete faithful plan with no validation errors.
Naming multiple formats and asking their counts is sufficient to request separate per-format counts; do not require the user to say '각각'. An explicit combined total overrides this default.
Reason must be short Korean. Return only the review JSON schema."""

OPEN_REVIEW = """Validate the ARGUMENT SELECTION for an image-open operation.
Execution is already fixed: executor runs the candidate query on image layers, extracts real paths, then calls photoshop_open_images.
The candidate is ONLY the query selecting targets. It must NOT contain an open command or tool name.
Do not reject a target query for not opening Photoshop itself: that is the executor's next step, not a query field.
Check explicit image-open intent in original_request, requested target scope, format/name filters, ordinal offset and count.
If no format is requested do not restrict image formats. Source rows already include only compatible raster images.
First/second without a size/name criterion uses existing list order, so order_by=[] is valid.
Require aggregate=null. No generated paths or code are permitted. Validate requested selection without inventing extra filters.
For compound requests only review current_task. Other tools execute separately.
Choose accept for a faithful selection, repair for all necessary changes, unsupported/clarify if intent or scope cannot be established.
Return the review JSON schema with a short Korean reason."""


def summary(query, result):
    notice = ""
    if result.get("is_partial"):
        excluded = result.get("excluded_count", 0)
        notice = (f"\n※ 정보 미확인 {excluded}개 제외. 전체 결과와 다를 수 있습니다." if excluded else
                  "\n※ 이전 조회에서 제외된 항목이 있어 전체 결과와 다를 수 있습니다.")
    elif result.get("warnings"):
        notice = "\n※ 일부 항목은 확인 불가입니다."
    if result["aggregate"]:
        labels = {"count": "개수", "sum": "합계", "avg": "평균", "min": "최솟값", "max": "최댓값"}
        operation = query.aggregate
        def number(value):
            if operation.field == "size_bytes" and operation.function != "count" and value is not None:
                return format_size(value)
            return "계산할 데이터 없음" if value is None else f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
        records = result["records"]
        values = [f"{record['group']}: {number(record['value'])}" if query.group_by else number(record["value"]) for record in records[:3]]
        unit = "개" if operation.function == "count" else ""
        target = "레이어" if operation.field == "*" else "파일 크기" if operation.field == "size_bytes" else FIELD_LABELS.get(operation.field, "조회 항목")
        more = f"\n외 {len(records) - 3}개 항목은 상세 표에서 확인하세요." if len(records) > 3 else ""
        return f"{target} {labels[operation.function]}: " + "; ".join(values) + (f" {unit}" if unit else "") + more + notice
    records = result["records"]
    if not records:
        return (f"{query.offset + 1}번째에 해당하는 결과가 없습니다." if query.offset else "조건에 맞는 레이어가 없습니다.") + notice
    head = ""
    if query.order_by and query.order_by[0].field == "size_bytes":
        direction = "큰" if query.order_by[0].direction == "desc" else "작은"
        head = f"용량이 {direction} 순서로 {query.offset + 1}번째 파일입니다." if len(records) == 1 else f"용량이 {direction} 순서입니다."
    elif len(records) > 1:
        head = f"레이어 {result['count']}개" + (" (앞 3개)" if len(records) > 3 else "")
    # Output is generated from selected fields, not an unchecked model answer.
    def display(key, value):
        if value is None:
            return "확인 불가"
        if key == "size_bytes":
            return format_size(value)
        if key == "visible":
            return "표시" if value else "숨김"
        if key == "kind":
            return {"raster": "영상", "vector": "벡터"}.get(value, value)
        return str(value)
    # Chat is a preview, not a dump of the model-selected projection. Preserve
    # every column in records for the separate detail table.
    lines = []
    for record in records[:3]:
        keys = [key for key in ("name", "kind", "size_bytes") if key in record]
        if "name" not in record:
            keys = [key for key in ("extension", "kind", "visible", "size_bytes") if key in record][:3]
        if keys:
            prefix = f"{record['number']}. " if "number" in record else ""
            lines.append(prefix + " · ".join(display(key, record[key]) for key in keys))
    if not lines:
        lines = [f"조회 결과 {len(records)}개입니다. 상세 표에서 확인하세요."]
    more = f"\n외 {len(records) - 3}개는 상세 표에서 확인하세요." if len(records) > 3 else ""
    return (head + "\n" if head else "") + "\n".join(lines) + more + notice


class GeneralAgent:
    def __init__(self, busy):
        self.busy = busy
        self.sessions = OrderedDict()

    def get_session(self, client, session_id, connection):
        now = time.monotonic()
        for key, value in list(self.sessions.items()):
            if now - value.touched > 1800:
                del self.sessions[key]
        key = (client, session_id) if session_id else None
        value = self.sessions.get(key) if key else None
        if value is None or value.connection_id != connection.connection_id:
            value = Session(connection.connection_id)
        return key, copy.deepcopy(value)

    def save(self, key, session):
        if key:
            session.touched = time.monotonic()
            self.sessions[key] = session
            self.sessions.move_to_end(key)
            while len(self.sessions) > 128:
                self.sessions.popitem(last=False)

    async def run(self, state, body):
        if body.client_id in self.busy:
            raise ExecutionError(409, "agent_busy", "해당 프로그램의 AI 요청이 진행 중입니다.")
        connection = state.connections.connections.get(body.client_id)
        if connection is None:
            raise ExecutionError(503, "client_offline", "벡터 프로그램 연결을 확인하세요.")
        self.busy.add(body.client_id)
        trace, requested, parts, result = [], [], [], None
        completed_tasks, planned_tasks = 0, 0
        model = state.settings.ollama_model

        def respond(warning=None):
            status = ("completed" if planned_tasks and completed_tasks == planned_tasks else
                      "partial" if completed_tasks else "failed" if planned_tasks else "unverified")
            if any(item.result and item.result.get("is_partial") for item in trace if item.tool_name == "query_layers"):
                status = "partial"
                warning = warning or "incomplete_data"
            if any(item.tool_name == OPEN_TOOL and item.result and item.result.get("failures") for item in trace):
                status = "partial" if any(item.tool_name == OPEN_TOOL and item.result and item.result.get("documents") for item in trace) else "failed"
            content = "\n\n".join(parts) or "요청을 실행하지 않았습니다."
            if len(content) > 15000:
                content = content[:14900] + "\n답변을 일부 생략했습니다. 실제 결과는 상세 조회 결과에서 확인할 수 있습니다."
            return AgentChatResponse(request_id=str(uuid4()), model=model, client_id=body.client_id,
                session_id=body.session_id, message=ChatMessage(role="assistant", content=content),
                done_reason="stop", tool_results=trace, requested_tools=list(dict.fromkeys(requested)),
                missing_tools=[] if status == "completed" else list(dict.fromkeys(requested[completed_tasks:])),
                completion_status=status, warning=warning, query_result=result)

        try:
            async with asyncio.timeout(state.settings.agent_timeout_seconds):
                key, session = self.get_session(body.client_id, body.session_id, connection)
                def attach_reference(data, rows):
                    session.numbered_rows = copy.deepcopy(rows)
                    session.reference_id = uuid4().hex
                    data["records"] = [{**record, "number": index} for index, record in enumerate(data["records"], 1)]
                    # Keep the explicit number first in the detail table.
                    data["records"] = [{"number": record["number"], **record} for record in data["records"]]
                    data["reference_id"] = session.reference_id
                    self.save(key, session)
                    return data
                question = next((message.content for message in reversed(body.messages) if message.role == "user"), "")
                if not question:
                    raise QueryError("사용자 질문이 필요합니다.")
                question = expand_count_request(question)
                catalog = await asyncio.to_thread(state.registry.get_tools, body.client_id)
                available_tools = {tool.name for tool in catalog.tools}
                available_fields = BASE_FIELDS | (FILE_FIELDS if "get_layer_metadata" in available_tools else set())
                context = lambda: {"previous_result_available": session.rows is not None,
                                   "previous_count": len(session.rows) if session.rows is not None else None,
                                   "previous_query": session.last_query, "previous_limitations": session.limitations,
                                   "numbered_list_available": session.numbered_rows is not None,
                                   "numbered_list_count": len(session.numbered_rows) if session.numbered_rows is not None else None,
                                   "reference_id": session.reference_id}
                # Preserve incomplete-result scope for subsequent questions.
                capabilities = {name: FIELDS[name] for name in sorted(available_fields)}
                route_tools = available_tools | {"query_layers"} | ({"open_numbered_images"} if OPEN_TOOL in available_tools else set())
                task_payload = await state.ollama.chat([
                    {"role": "system", "content": ROUTE + "\nAvailable tools: " + json.dumps(sorted(route_tools)) + "\nOutput schema: " + json.dumps(schema(Tasks)) + "\nLayer fields: " + json.dumps(capabilities, ensure_ascii=False)},
                    {"role": "assistant", "content": json.dumps(context(), ensure_ascii=False)},
                    {"role": "user", "content": question},
                ], response_schema=schema(Tasks))
                model = task_payload["model"]
                tasks = Tasks.model_validate_json(task_payload["message"]["content"]).tasks
                log.info("Query routing client=%s tasks=%s", body.client_id, [task.model_dump() for task in tasks])
                planned_tasks = len(tasks)
                requested = [OPEN_TOOL if task.tool == "open_numbered_images" else task.tool for task in tasks]
                # Refuse unsupported plans as a whole, before touching a desktop tool.
                if any(task.tool in {"unsupported", "clarify"} for task in tasks):
                    log.info("Query routing refused client=%s tasks=%s", body.client_id, [task.model_dump() for task in tasks])
                    parts.append("이 요청에 필요한 기능이 제공되지 않거나 조회 대상을 확정하지 못해 실행하지 않았습니다.")
                    return respond("clarification_required")
                if sum(task.tool in {OPEN_TOOL, "open_numbered_images"} for task in tasks) > 1:
                    raise TargetError("한 요청에는 이미지 열기 작업을 하나로 지정해 주세요.")
                if any(task.tool != "query_layers" and (OPEN_TOOL if task.tool == "open_numbered_images" else task.tool) not in available_tools for task in tasks):
                    raise TargetError("필요한 포토샵 도구가 등록되지 않았습니다. 벡터 프로그램을 업데이트한 뒤 재실행해 주세요.")
                snapshots = {}

                async def snapshot(name, arguments=None):
                    if name in snapshots and arguments is None:
                        return snapshots[name]
                    if state.connections.connections.get(body.client_id) is not connection:
                        raise QueryError("연결이 변경되어 요청을 중단했습니다.")
                    current = await asyncio.to_thread(state.registry.get_tools, body.client_id)
                    if not any(tool.name == name for tool in current.tools):
                        raise QueryError("필요한 도구가 현재 프로그램에 등록되어 있지 않습니다: " + name)
                    seconds = 180 if name == OPEN_TOOL else 60 if name.startswith("photoshop_") else 15
                    value = await state.connections.call(body.client_id, ToolCallRequest(tool_name=name, arguments=arguments or {}, timeout_seconds=seconds))
                    trace.append(AgentToolResult(tool_name=name, **value.model_dump()))
                    if value.status != "succeeded":
                        raise QueryError("실제 도구 실행 결과를 확인하지 못했습니다.")
                    if arguments is None:
                        snapshots[name] = value.result
                    return value.result

                for task_index, task in enumerate(tasks):
                    if task.tool == "open_numbered_images":
                        if session.numbered_rows is None:
                            raise TargetError("먼저 레이어 목록을 조회해 주세요. 가장 최근 조회 목록의 번호로 선택할 수 있습니다.")
                        if body.reference_id != session.reference_id:
                            raise TargetError("조회 목록이 바뀌었거나 확인되지 않아 열지 않았습니다. 레이어 목록을 다시 조회한 뒤 번호를 선택해 주세요.")
                        try:
                            selected = select_positions(session.numbered_rows, task.numbers)
                        except QueryError as exc:
                            raise TargetError(str(exc)) from exc
                        if len(selected) > 5:
                            raise TargetError("한 번에 최대 5개 번호까지 지정해 주세요. 이번에는 열지 않았습니다.")
                        from pathlib import PurePosixPath
                        if any(row.get("kind") != "raster" or not row.get("path") or
                               PurePosixPath(str(row["path"]).replace("\\", "/")).suffix.lower() not in IMAGE_EXTENSIONS for row in selected):
                            raise TargetError("선택 번호에 이미지가 아닌 레이어가 있습니다. 번호를 다시 확인해 주세요. 이번에는 열지 않았습니다.")
                        data = await snapshot(OPEN_TOOL, {"paths": [row["path"] for row in selected]})
                        parts.append(describe(OPEN_TOOL, data))
                        if data.get("failures"):
                            return respond("photoshop_open_partial")
                        if not data.get("documents"):
                            raise TargetError("포토샵에서 열린 작업 문서를 확인하지 못했습니다.")
                    elif task.tool in READ_TOOLS:
                        data = await snapshot(task.tool)
                        parts.append(describe(task.tool, data))
                    elif task.tool == "photoshop_ping":
                        data = await snapshot("photoshop_ping")
                        parts.append("포토샵 통신에 성공했습니다." if data.get("connected") is True else "포토샵 통신 성공을 확인하지 못했습니다.")
                    else:
                        opening = task.tool == OPEN_TOOL
                        operation_rules = ("\nThis subtask explicitly opens images in Photoshop. Produce ONLY a nonaggregate query selecting target image rows. "
                                           "Use name/path as selection columns. Apply the requested filters, ordering, offset and limit. "
                                           "Do not change a requested batch count to fit limits; a maximum of 5 targets is enforced by the executor. "
                                           "Source rows are already restricted to compatible image layers. No image format requested means where=[]; do NOT assume TIFF. "
                                           "Supported formats: " + ",".join(sorted(IMAGE_EXTENSIONS)) + ". "
                                           "First/second without a sorting criterion means current list order (order_by=[]). Never invent paths."
                                           if opening else "")
                        plan_payload = await state.ollama.chat([
                            {"role": "system", "content": PLAN + operation_rules + "\nOutput schema: " + json.dumps(schema(Query)) + "\nAvailable fields: " + json.dumps(capabilities, ensure_ascii=False)},
                            {"role": "assistant", "content": json.dumps(context(), ensure_ascii=False)},
                            *([{"role": "user", "content": question}, {"role": "assistant", "content": "Preserve original constraints while planning the following subtask."}] if len(tasks) > 1 else []),
                            {"role": "user", "content": question if len(tasks) == 1 else task.request},
                        ], response_schema=schema(Query))
                        for attempt in range(2):
                            query = None
                            problem = None
                            try:
                                query = Query.model_validate_json(plan_payload["message"]["content"])
                                unknown = query.fields() - available_fields - ({"group", "value"} if query.aggregate else set())
                                if unknown:
                                    validate_query(query, available_fields)  # Unavailable fields are terminal.
                                validate_query(query, available_fields)
                            except ValidationError as exc:
                                problem = str(exc)[:1500]
                            except QueryError as exc:
                                if query and query.fields() - available_fields - ({"group", "value"} if query.aggregate else set()):
                                    raise
                                problem = str(exc)
                            log.info("Query candidate client=%s task=%s attempt=%s candidate=%s validation=%s",
                                     body.client_id, task_index, attempt + 1, plan_payload["message"]["content"], problem)
                            review_payload = await state.ollama.chat([
                                {"role": "system", "content": (OPEN_REVIEW if opening else REVIEW) + "\nQuery language capabilities: " + PLAN + operation_rules
                                 + "\nSupported query schema: " + json.dumps(schema(Query)) + "\nOutput schema: " + json.dumps(schema(Review))},
                                {"role": "user", "content": json.dumps({
                                    "request": task.request if len(tasks) > 1 else question, "original_request": question,
                                    "current_task": task.request,
                                    "execution_operation": task.tool,
                                    "task_index": task_index, "task_plan": [value.model_dump() for value in tasks],
                                    "available_fields": capabilities, "available_tools": sorted(available_tools), "session": context(),
                                    "candidate": query.model_dump() if query else plan_payload["message"]["content"],
                                    "validation_error": problem,
                                }, ensure_ascii=False)},
                            ], response_schema=schema(Review))
                            review = Review.model_validate_json(review_payload["message"]["content"])
                            log.info("Query review client=%s task=%s attempt=%s review=%s", body.client_id, task_index, attempt + 1, review.model_dump())
                            if review.decision in {"unsupported", "clarify"}:
                                raise PlanningError(review.reason or "요청한 정보를 확인할 수 없습니다.")
                            if review.decision == "accept" and not problem:
                                break
                            if attempt:
                                raise PlanningError(review.reason or problem or "조회 계획을 확정하지 못했습니다.")
                            plan_payload = await state.ollama.chat([
                                {"role": "system", "content": PLAN + operation_rules + "\nOutput schema: " + json.dumps(schema(Query)) + "\nAvailable fields: " + json.dumps(capabilities, ensure_ascii=False)},
                                {"role": "assistant", "content": json.dumps({"session": context(),
                                    "rejected_query": query.model_dump() if query else plan_payload["message"]["content"],
                                    "review": review.reason, "validation_error": problem}, ensure_ascii=False)},
                                {"role": "system", "content": "Repair the rejected query using the errors and original request below. Return a complete replacement query, not an explanation. Preserve the original scope and filters. If row identity is required, replace numeric aggregation with row sorting and select the identity and numeric field."},
                                {"role": "user", "content": question if len(tasks) == 1 else task.request},
                            ], response_schema=schema(Query))
                        if query.source == "previous_result" and session.rows is None:
                            raise QueryError("이 대화에 이전 조회 결과가 없습니다. 현재 조회 대상인지 확인해 주세요.")
                        needs_files = bool(query.fields() & FILE_FIELDS)
                        log.info("Query plan client=%s task=%s plan=%s", body.client_id, task_index, json.dumps(query.model_dump(), ensure_ascii=False))
                        name = "get_layer_metadata" if needs_files else "get_layer_list"
                        if query.source == "current":
                            data = await snapshot(name)
                            rows = data.get("layers")
                            if (not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows)
                                    or type(data.get("count")) is not int or data["count"] != len(rows)
                                    or len(json.dumps(rows).encode("utf-8")) > 1024 * 1024):
                                raise QueryError("전체 메타데이터를 받지 못해 결과를 계산하지 않았습니다.")
                        else:
                            rows = session.rows
                            if needs_files and any(any(row.get(field) is None for field in query.fields() & FILE_FIELDS) for row in rows):
                                metadata = await snapshot("get_layer_metadata")
                                lookup = {(row.get("path"), row.get("kind")): row for row in metadata.get("layers", []) if isinstance(row, dict) and row.get("path")}
                                rows = [{**row, **{field: lookup.get((row.get("path"), row.get("kind")), {}).get(field) for field in FILE_FIELDS}} for row in rows]
                        if opening:
                            if query.aggregate:
                                raise TargetError("열 이미지 목록을 확정하지 못했습니다. 파일 이름이나 개수를 지정해 주세요.")
                            from pathlib import PurePosixPath
                            rows = [row for row in rows if row.get("kind") == "raster" and
                                    PurePosixPath(str(row.get("path") or "").replace("\\", "/")).suffix.lower() in IMAGE_EXTENSIONS]
                        computed = execute(query, rows, available_fields)
                        if opening:
                            candidates = computed["rows"]
                            matched = computed["count"]
                            if matched > 5 and (len(candidates) > 5 or task.requested_count is None):
                                full = execute(query.model_copy(update={"offset": 0, "limit": 1000}), rows, available_fields)
                                full_rows = full.pop("rows")
                                full["records"] = [{name: row.get(name) for name in ("name", "extension", "kind", "visible")} for row in full_rows]
                                result = attach_reference({**full, "plan": query.model_dump(), "query": {"output": "list"}, "layers": []}, full_rows)
                                trace.append(AgentToolResult(tool_name="query_layers", call_id=uuid4().hex, status="succeeded", result=result))
                            if task.requested_count is None and (query.offset or len(candidates) < matched):
                                if matched > 5:
                                    raise TargetError(f"대상 이미지가 {matched}개입니다. 한 번에 최대 5개까지 열 수 있어 이번에는 열지 않았습니다.\n상세 목록 번호로 지정해 주세요. 예: 1,2,4번 파일 열어줘.")
                                raise TargetError("전체 대상과 선택된 개수가 달라 열지 않았습니다. 열 파일이나 개수를 지정해 주세요.")
                            if task.requested_count is not None and len(candidates) != min(task.requested_count, max(0, matched - query.offset)):
                                raise TargetError("요청한 개수와 선택된 개수가 달라 열지 않았습니다. 대상을 다시 지정해 주세요.")
                            if len(candidates) > 5:
                                raise TargetError(f"대상 이미지가 {len(candidates)}개입니다. 한 번에 최대 5개까지 열 수 있습니다. 상세 목록 번호로 지정해 주세요. 예: 1,2,4번 파일 열어줘.")
                        if query.source == "previous_result" and session.limitations:
                            computed["is_partial"] = True
                            computed["warnings"] = list(dict.fromkeys(session.limitations + computed["warnings"]))
                        session.limitations = computed["warnings"][:] if computed["is_partial"] else []
                        log.info("Query result client=%s count=%s excluded=%s warnings=%s", body.client_id, computed["count"], computed["excluded_count"], computed["warnings"])
                        session.rows = computed.pop("rows")
                        session.last_query = query.model_dump()
                        self.save(key, session)
                        if opening:
                            targets = [row.get("path") for row in session.rows]
                            if computed["is_partial"]:
                                raise TargetError("정보가 누락되어 열 대상을 확정하지 못했습니다. 파일 이름으로 지정해 주세요.")
                            if not targets:
                                raise TargetError("조건에 맞는 이미지 파일이 없습니다.")
                            if len(targets) > 5:
                                raise TargetError(f"대상 이미지가 {len(targets)}개입니다. 한 번에 최대 5개씩 이름이나 개수를 지정해 주세요.")
                            data = await snapshot(OPEN_TOOL, {"paths": targets})
                            parts.append(describe(OPEN_TOOL, data))
                            if data.get("failures"):
                                return respond("photoshop_open_partial")
                            if not data.get("documents"):
                                raise TargetError("포토샵에서 열린 작업 문서를 확인하지 못했습니다.")
                            completed_tasks += 1
                            continue
                        result = {**computed, "plan": query.model_dump(), "query": {"output": "count" if query.aggregate else "list"},
                                  "layers": session.rows if not query.aggregate else []}
                        if not query.aggregate:
                            result = attach_reference(result, session.rows)
                        trace.append(AgentToolResult(tool_name="query_layers", call_id=uuid4().hex, status="succeeded", result=result))
                        parts.append(summary(query, result))
                    completed_tasks += 1
                return respond()
        except (QueryError, ValidationError, ExecutionError, OllamaError, TimeoutError) as exc:
            log.warning("Query failed client=%s error_type=%s reason=%s", body.client_id, type(exc).__name__, str(exc)[:1500])
            if isinstance(exc, (OllamaError, ExecutionError)) and not trace:
                raise
            if isinstance(exc, TimeoutError) and not trace:
                raise ExecutionError(504, "agent_timeout", "AI 요청 제한 시간이 초과되었습니다.") from exc
            message = (str(exc) if isinstance(exc, TargetError) else
                       "질문의 뜻에 맞는 조회 방법을 확정하지 못했습니다. 요청한 조회는 실행하지 않았습니다."
                       if isinstance(exc, PlanningError) else
                       "요청에 필요한 정보나 조회 대상을 확인하지 못했습니다. 확인하지 못한 결과를 추정해서 답하지 않았습니다."
                       if isinstance(exc, QueryError) else
                       "조회 처리 중 문제가 발생했습니다. 결과를 확인하지 못했으며 자동 재실행하지 않았습니다.")
            parts.append(message)
            return respond("query_not_executed" if isinstance(exc, QueryError) else "query_failed")
        finally:
            self.busy.discard(body.client_id)
