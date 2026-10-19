"""Composable read-only relational operations; never executes model-generated code."""
import math
import copy
import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FIELDS = {
    "name": "string: 레이어 이름", "extension": "string: 소문자 확장자(.tif 등)",
    "kind": "string: raster 또는 vector", "visible": "boolean: 표시 여부",
    "path": "string: 파일 경로", "size_bytes": "number: 파일 크기(바이트)",
    "modified_at": "number: 파일 수정 시각(Unix 초)",
}
BASE_FIELDS = {"name", "extension", "kind", "visible", "path"}
FILE_FIELDS = {"size_bytes", "modified_at"}
FIELD_LABELS = {"name": "이름", "size_bytes": "파일 크기(바이트)", "extension": "확장자", "kind": "종류",
                "visible": "표시 여부", "path": "경로", "modified_at": "수정 시각(Unix 초)"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Predicate(Strict):
    field: str = Field(min_length=1, max_length=64)
    operator: Literal["eq", "ne", "in", "contains", "gt", "ge", "lt", "le"]
    values: list[str] = Field(min_length=1, max_length=20)


class Sort(Strict):
    field: str = Field(min_length=1, max_length=64)
    direction: Literal["asc", "desc"]


class Aggregate(Strict):
    function: Literal["count", "sum", "avg", "min", "max"]
    field: str = Field(min_length=1, max_length=64)


class Query(Strict):
    source: Literal["current", "previous_result"]
    where: list[Predicate] = Field(max_length=8)
    select: list[str] = Field(min_length=1, max_length=8)
    order_by: list[Sort] = Field(max_length=3)
    offset: int = Field(default=0, ge=0, le=1000, description="Rows to skip after filtering and sorting; Nth item uses N-1")
    limit: int = Field(ge=1, le=1000)
    aggregate: Aggregate | None
    group_by: str | None

    def fields(self):
        fields = set(self.select) | {value.field for value in self.where} | {value.field for value in self.order_by}
        if self.aggregate and self.aggregate.field != "*":
            fields.add(self.aggregate.field)
        if self.group_by:
            fields.add(self.group_by)
        return fields


class QueryError(ValueError):
    pass


def select_positions(rows, numbers):
    """Select 1-based displayed row numbers without filtering or reindexing."""
    if not rows:
        raise QueryError("조회 목록이 비어 있습니다. 레이어 목록을 다시 조회해 주세요.")
    if not numbers or any(type(number) is not int or number < 1 or number > len(rows) for number in numbers):
        raise QueryError(f"목록 번호는 1~{len(rows)} 사이로 지정해 주세요. 이번에는 열지 않았습니다.")
    return [rows[number - 1] for number in dict.fromkeys(numbers)]


def schema(model):
    document = model.model_json_schema()
    definitions = document.pop("$defs", {})
    def expand(value):
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(definitions[value["$ref"].split("/")[-1]])
            return {key: expand(item) for key, item in value.items()}
        return [expand(item) for item in value] if isinstance(value, list) else value
    expanded = expand(document)
    if model is Query:
        expanded["required"] = list(dict.fromkeys(expanded["required"] + ["offset"]))
        # Separate mutually exclusive result shapes at generation time. The model
        # cannot combine file identities with a scalar aggregate or sort that
        # aggregate by an original data field. Python still validates every plan.
        rows, aggregate = copy.deepcopy(expanded), copy.deepcopy(expanded)
        rows["properties"]["aggregate"] = {"type": "null"}
        rows["properties"]["group_by"] = {"type": "null"}
        aggregate["properties"]["aggregate"] = expand(definitions["Aggregate"])
        aggregate["properties"]["select"]["items"] = {"type": "string", "enum": ["group", "value"]}
        aggregate["properties"]["order_by"]["items"]["properties"]["field"] = {"type": "string", "enum": ["group", "value"]}
        for branch in (rows, aggregate):
            # Decide result shape before choosing projection and ordering.
            branch["properties"] = {"aggregate": branch["properties"].pop("aggregate"), **branch["properties"]}
        return {"anyOf": [rows, aggregate]}
    return expanded


def validate_query(query, available):
    aggregate_fields = {"group", "value"} if query.aggregate else set()
    missing = query.fields() - set(available) - aggregate_fields
    if missing:
        raise QueryError("현재 제공되지 않는 정보입니다: " + ", ".join(sorted(missing)))
    for predicate in query.where:
        if predicate.field in aggregate_fields:
            raise QueryError("집계 결과 필드는 집계 전 필터에 사용할 수 없습니다.")
        if predicate.operator not in {"in", "eq", "ne"} and len(predicate.values) != 1:
            raise QueryError("범위·문자열 비교는 값 하나가 필요합니다.")
        if predicate.operator == "contains" and predicate.field not in {"name", "path", "extension", "kind"}:
            raise QueryError("문자열 포함 비교는 문자열 필드에만 사용할 수 있습니다.")
    if query.aggregate:
        if query.offset and not query.group_by:
            raise QueryError("단일 집계값에는 시작 위치를 지정할 수 없습니다.")
        if query.aggregate.field != "*" and query.aggregate.field not in available:
            raise QueryError("집계 대상은 원본 데이터 필드여야 합니다.")
        if query.aggregate.function != "count" and query.aggregate.field not in FILE_FIELDS:
            raise QueryError("숫자 집계에는 숫자 필드가 필요합니다.")
        if any(order.field not in {"group", "value", query.group_by} for order in query.order_by):
            raise QueryError("집계 후 정렬은 group/value 필드를 사용하세요.")
    elif query.group_by:
        raise QueryError("그룹별 조회에는 집계 연산이 필요합니다.")


def normalize(rows):
    normalized = []
    for row in rows:
        value = dict(row)
        for name in FILE_FIELDS:
            number = value.get(name)
            if number is not None and (type(number) not in {int, float} or number < 0 or not math.isfinite(number)):
                value[name] = None
        value["extension"] = PurePosixPath(str(row.get("path") or row.get("name") or "").replace("\\", "/")).suffix.lower()
        normalized.append(value)
    return normalized


def literal(field, value):
    if field == "visible":
        if value.lower() not in {"true", "false"}:
            raise QueryError("표시 여부 값은 true 또는 false여야 합니다.")
        return value.lower() == "true"
    if field in FILE_FIELDS:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?\s*", value, re.I)
        if not match:
            raise QueryError("숫자 또는 명시적인 용량 단위가 필요합니다.")
        units = {"b": 1, "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4,
                 "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}
        result = float(match[1]) * units.get((match[2] or "b").lower(), 1)
        if not math.isfinite(result):
            raise QueryError("유효한 숫자가 필요합니다.")
        return result
    return ("." + value.lower().lstrip(".")) if field == "extension" else value


def execute(query, rows, available):
    validate_query(query, available)
    selected = normalize(rows)
    excluded = {}
    def known(candidates, fields):
        retained = []
        for row in candidates:
            missing = {field for field in fields if row.get(field) is None}
            if missing:
                excluded.setdefault(id(row), set()).update(missing)
            else:
                retained.append(row)
        return retained

    def quality(records):
        missing_display = sum(any(value is None for name, value in record.items()
                                  if not (query.aggregate and not query.group_by and name == "group"))
                              for record in records)
        warnings = []
        if excluded:
            fields = sorted(set().union(*excluded.values()))
            warnings.append(f"{len(excluded)}개 레이어의 연산에 필요한 정보({', '.join(FIELD_LABELS.get(field, field) for field in fields)})를 확인하지 못해 제외했습니다. "
                            "결과는 확인된 데이터 기준이며, 전체 대상의 개수·순위·계산값은 확정할 수 없습니다.")
        if missing_display:
            warnings.append(f"결과 {missing_display}행의 일부 값은 확인 불가입니다.")
        return {"is_partial": bool(excluded), "excluded_count": len(excluded), "warnings": warnings}

    for predicate in query.where:
        selected = known(selected, {predicate.field})
        values = [literal(predicate.field, value) for value in predicate.values]
        def match(row):
            actual, target = row[predicate.field], values[0]
            return {"eq": lambda: actual in values, "ne": lambda: actual not in values,
                    "in": lambda: actual in values, "contains": lambda: target in actual,
                    "gt": lambda: actual > target, "ge": lambda: actual >= target,
                    "lt": lambda: actual < target, "le": lambda: actual <= target}[predicate.operator]()
        try:
            selected = [row for row in selected if match(row)]
        except TypeError as exc:
            raise QueryError("필드와 비교 값의 자료형이 맞지 않습니다.") from exc
    if query.aggregate:
        operation = query.aggregate
        selected = known(selected, ({operation.field} if operation.field != "*" and operation.function != "count" else set()) | ({query.group_by} if query.group_by else set()))
        groups = {}
        for row in selected:
            groups.setdefault(row.get(query.group_by) if query.group_by else None, []).append(row)
        if not groups and not query.group_by:
            groups[None] = []
        records = []
        for key, group in groups.items():
            numbers = [row.get(operation.field) for row in group] if operation.field != "*" else []
            if operation.function == "count": value = len(group) if operation.field == "*" else sum(number is not None for number in numbers)
            elif operation.function == "sum": value = sum(numbers) if numbers or not excluded else None
            elif not numbers: value = None
            elif operation.function == "avg": value = sum(numbers) / len(numbers)
            elif operation.function == "min": value = min(numbers)
            else: value = max(numbers)
            records.append({"group": key, "value": value})
        for order in reversed(query.order_by):
            name = "group" if order.field == query.group_by else order.field
            records.sort(key=lambda row: (row[name] is not None, row[name]), reverse=order.direction == "desc")
        page = records[query.offset:query.offset + query.limit]
        return {"count": len(selected), "rows": selected, "records": page, "aggregate": operation.model_dump(), "truncated": len(records) > len(page), **quality(page)}
    selected = known(selected, {order.field for order in query.order_by})
    try:
        for order in reversed(query.order_by):
            selected.sort(key=lambda row: row[order.field], reverse=order.direction == "desc")
    except TypeError as exc:
        raise QueryError("정렬 필드의 자료형이 일치하지 않습니다.") from exc
    chosen = selected[query.offset:query.offset + query.limit]
    records = [{name: row.get(name) for name in query.select} for row in chosen]
    return {"count": len(selected), "rows": chosen,
            "records": records,
            "aggregate": None, "truncated": len(selected) > len(chosen), **quality(records)}
