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

from app.agent.query_engine import BASE_FIELDS, FIELDS, FILE_FIELDS, Query, QueryError, execute, schema, validate_query
from app.execution.connections import ExecutionError
from app.llm.ollama import OllamaError
from app.schemas.agent import AgentChatResponse, AgentToolResult
from app.schemas.chat import ChatMessage
from app.schemas.execution import ToolCallRequest

log = logging.getLogger("uvicorn.error.agent.general")


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool: Literal["query_layers", "photoshop_ping", "unsupported", "clarify"]
    request: str = Field(min_length=1, max_length=4000)


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
    touched: float = field(default_factory=time.monotonic)


ROUTE = """You plan read-only desktop work. Return ordered tasks, never answers.
query_layers: inspect layer metadata, filters, sorting, top-N, counts, numeric aggregates and grouping.
photoshop_ping: check Photoshop communication, not document editing.
unsupported: requested ability does not exist (editing, deletion, synthesis, etc).
clarify: target or intent cannot be determined from the current question and session.
Split independently requested outputs into tasks (at most 3), preserving their dependencies and constraints.
Do not replace unsupported requests with a similar supported operation. Do not answer a size/ranking request with a count.
Task request must preserve the meaning of the original Korean request. Prefer the user's original wording.
No task is executed until its tool and arguments pass validation."""

PLAN = """Translate the layer question into a read-only relational query, not an answer.
source=current reads current layer metadata; previous_result filters the last returned result.
where predicates are ANDed. Values are strings, including 'true'/'false' for booleans and units for sizes.
eq/in accept one or more alternatives, ne excludes all listed alternatives. Range/contains take one value.
TIFF includes .tif and .tiff: use extension in [".tif",".tiff"]. No extension restriction means where=[].
select lists fields to display. order_by sorts (asc/desc); limit controls returned row count.
For largest/smallest FILE, return the name and size_bytes, sort size_bytes, limit=1, aggregate=null.
For count: aggregate={function:count,field:*}. For total/average numeric values use sum/avg.
Grouped aggregate rows have group/value columns; order_by can sort those columns.
For numeric min/max only (no file identity requested), aggregate=min/max. group_by groups aggregates, otherwise null.
For plain lists use aggregate=null, group_by=null. Never turn unknown fields into count or drop requested constraints.
Use only fields required by the request. A plain layer list needs name/kind/visible, not file size or modification time.
Do not add sorting, file fields or filters unless required by the user's intent. Display-only missing values do not prevent listing a layer.
Field names are free strings so missing fields can be represented honestly: the server will reject unavailable fields.
If the user requests unavailable resolution, for example, reference resolution rather than pretending name/count answers it.
Use previous_result only when it exists or an earlier task in this request produces it; otherwise it remains unresolved.
Return exactly the query schema. Do not invent field values, paths, numeric results, code or SQL."""

REVIEW = """Independently check whether a read-only query fulfills the user's original intent.
Do not execute, answer, or assume valid JSON means a correct plan.
Check the requested output (identity, ordering/top-N, count, total, average, grouping), fields,
all filters, units, and previous-result scope. Use only the declared available capabilities.
Reject unnecessary file fields or ordering for a plain list; prefer the minimum information needed to fulfill the request.
Evaluate the current task within the whole task plan; another task may cover another requested output.
Never allow an unsupported concept in the original request to be replaced silently by a supported task.
If a requested concept needs unavailable information, choose unsupported; do not substitute another field.
If the query drops constraints or uses the wrong operation, choose repair and explain how to preserve the original request.
If the request is ambiguous choose clarify. Accept only a complete faithful plan with no validation errors.
Reason must be short Korean. Return only the review JSON schema."""


def summary(query, result):
    scope = "직전 조회 결과" if query.source == "previous_result" else "현재 레이어"
    if result.get("is_partial"):
        scope += " 중 확인된 데이터"
    notice = "\n" + "\n".join(result["warnings"]) if result.get("warnings") else ""
    if result["aggregate"]:
        labels = {"count": "개수", "sum": "합계", "avg": "평균", "min": "최솟값", "max": "최댓값"}
        operation = query.aggregate
        def number(value):
            return "계산할 데이터 없음" if value is None else f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
        records = result["records"]
        values = [f"{record['group']}: {number(record['value'])}" if query.group_by else number(record["value"]) for record in records[:10]]
        unit = "바이트" if operation.field == "size_bytes" else "개" if operation.function == "count" else ""
        return f"{scope} 조건 조회 — {operation.field} {labels[operation.function]}: " + "; ".join(values) + (f" {unit}" if unit else "") + notice
    labels = {"name": "이름", "size_bytes": "파일 크기(바이트)", "extension": "확장자", "kind": "종류", "visible": "표시 여부", "path": "경로", "modified_at": "수정 시각(Unix 초)"}
    sort = ", ".join(labels.get(order.field, order.field) + (" 내림차순" if order.direction == "desc" else " 오름차순") for order in query.order_by)
    head = f"{scope} 조건에 맞는 {result['count']}개 중 {len(result['records'])}개를 반환했습니다."
    if sort:
        head += " 정렬: " + sort + "."
    # Output is generated from selected fields, not an unchecked model answer.
    lines = [", ".join(f"{labels.get(key, key)}: {value if value is not None else '확인 불가'}" for key, value in record.items()) for record in result["records"][:5]]
    return head + ("\n" + "\n".join(lines) if lines else "") + notice


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
                question = next((message.content for message in reversed(body.messages) if message.role == "user"), "")
                if not question:
                    raise QueryError("사용자 질문이 필요합니다.")
                catalog = await asyncio.to_thread(state.registry.get_tools, body.client_id)
                available_tools = {tool.name for tool in catalog.tools}
                available_fields = BASE_FIELDS | (FILE_FIELDS if "get_layer_metadata" in available_tools else set())
                context = lambda: {"previous_result_available": session.rows is not None,
                                   "previous_count": len(session.rows) if session.rows is not None else None,
                                   "previous_query": session.last_query, "previous_limitations": session.limitations}
                # Preserve incomplete-result scope for subsequent questions.
                capabilities = {name: FIELDS[name] for name in sorted(available_fields)}
                task_payload = await state.ollama.chat([
                    {"role": "system", "content": ROUTE + "\nOutput schema: " + json.dumps(schema(Tasks)) + "\nLayer fields: " + json.dumps(capabilities, ensure_ascii=False)},
                    {"role": "assistant", "content": json.dumps(context(), ensure_ascii=False)},
                    {"role": "user", "content": question},
                ], response_schema=schema(Tasks))
                model = task_payload["model"]
                tasks = Tasks.model_validate_json(task_payload["message"]["content"]).tasks
                planned_tasks = len(tasks)
                requested = [task.tool for task in tasks]
                # Refuse unsupported plans as a whole, before touching a desktop tool.
                if any(task.tool in {"unsupported", "clarify"} for task in tasks):
                    parts.append("이 요청을 지원 기능만으로 확정할 수 없어 실행하지 않았습니다.\n" + "\n".join(task.request for task in tasks if task.tool in {"unsupported", "clarify"}))
                    return respond("clarification_required")
                snapshots = {}

                async def snapshot(name):
                    if name in snapshots:
                        return snapshots[name]
                    if state.connections.connections.get(body.client_id) is not connection:
                        raise QueryError("연결이 변경되어 요청을 중단했습니다.")
                    current = await asyncio.to_thread(state.registry.get_tools, body.client_id)
                    if not any(tool.name == name for tool in current.tools):
                        raise QueryError("필요한 도구가 현재 프로그램에 등록되어 있지 않습니다: " + name)
                    value = await state.connections.call(body.client_id, ToolCallRequest(tool_name=name, arguments={}, timeout_seconds=60 if name == "photoshop_ping" else 15))
                    trace.append(AgentToolResult(tool_name=name, **value.model_dump()))
                    if value.status != "succeeded":
                        raise QueryError("실제 도구 실행 결과를 확인하지 못했습니다.")
                    snapshots[name] = value.result
                    return value.result

                for task_index, task in enumerate(tasks):
                    if task.tool == "photoshop_ping":
                        data = await snapshot("photoshop_ping")
                        parts.append("포토샵 통신에 성공했습니다." if data.get("connected") is True else "포토샵 통신 성공을 확인하지 못했습니다.")
                    else:
                        plan_payload = await state.ollama.chat([
                            {"role": "system", "content": PLAN + "\nOutput schema: " + json.dumps(schema(Query)) + "\nAvailable fields: " + json.dumps(capabilities, ensure_ascii=False)},
                            {"role": "assistant", "content": json.dumps(context(), ensure_ascii=False)},
                            *([{"role": "user", "content": question}, {"role": "assistant", "content": "Preserve original constraints while planning the following subtask."}] if len(tasks) > 1 else []),
                            {"role": "user", "content": question if len(tasks) == 1 else task.request},
                        ], response_schema=schema(Query))
                        for attempt in range(2):
                            query = None
                            problem = None
                            try:
                                query = Query.model_validate_json(plan_payload["message"]["content"])
                                if query.fields() - available_fields:
                                    validate_query(query, available_fields)  # Unavailable fields are terminal.
                                validate_query(query, available_fields)
                            except ValidationError as exc:
                                problem = str(exc)[:1500]
                            except QueryError as exc:
                                if query and query.fields() - available_fields:
                                    raise
                                problem = str(exc)
                            review_payload = await state.ollama.chat([
                                {"role": "system", "content": REVIEW + "\nQuery language capabilities: " + PLAN
                                 + "\nSupported query schema: " + json.dumps(schema(Query)) + "\nOutput schema: " + json.dumps(schema(Review))},
                                {"role": "user", "content": json.dumps({
                                    "request": question, "current_task": task.request,
                                    "task_index": task_index, "task_plan": [value.model_dump() for value in tasks],
                                    "available_fields": capabilities, "session": context(),
                                    "candidate": query.model_dump() if query else plan_payload["message"]["content"],
                                    "validation_error": problem,
                                }, ensure_ascii=False)},
                            ], response_schema=schema(Review))
                            review = Review.model_validate_json(review_payload["message"]["content"])
                            if review.decision in {"unsupported", "clarify"}:
                                raise QueryError(review.reason or "요청한 정보를 확인할 수 없습니다.")
                            if review.decision == "accept" and not problem:
                                break
                            if attempt:
                                raise QueryError(review.reason or problem or "조회 계획을 확정하지 못했습니다.")
                            plan_payload = await state.ollama.chat([
                                {"role": "system", "content": PLAN + "\nOutput schema: " + json.dumps(schema(Query)) + "\nAvailable fields: " + json.dumps(capabilities, ensure_ascii=False)},
                                {"role": "assistant", "content": json.dumps({"session": context(), "review": review.reason, "validation_error": problem}, ensure_ascii=False)},
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
                        computed = execute(query, rows, available_fields)
                        if query.source == "previous_result" and session.limitations:
                            computed["is_partial"] = True
                            computed["warnings"] = list(dict.fromkeys(session.limitations + computed["warnings"]))
                        session.limitations = computed["warnings"][:] if computed["is_partial"] else []
                        log.info("Query result client=%s count=%s excluded=%s warnings=%s", body.client_id, computed["count"], computed["excluded_count"], computed["warnings"])
                        session.rows = computed.pop("rows")
                        session.last_query = query.model_dump()
                        self.save(key, session)
                        result = {**computed, "plan": query.model_dump(), "query": {"output": "count" if query.aggregate else "list"},
                                  "layers": session.rows if not query.aggregate else []}
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
            message = str(exc) if isinstance(exc, QueryError) else "조회 계획 또는 실행 결과를 확인하지 못했습니다. 자동 재실행하지 않았습니다."
            parts.append(message)
            return respond("query_not_executed" if isinstance(exc, QueryError) else "query_failed")
        finally:
            self.busy.discard(body.client_id)
