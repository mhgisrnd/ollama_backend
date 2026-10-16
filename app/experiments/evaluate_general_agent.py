"""Development evaluation of generic operations without editing .env or production data."""
import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.agent.general import GeneralAgent
from app.core.config import Settings
from app.llm.ollama import OllamaClient, OllamaError
from app.execution.connections import ExecutionError
from app.schemas.agent import AgentChatRequest
from app.schemas.execution import ToolResult

ROWS = [
    {"name": "small.tif", "path": "small.tif", "kind": "raster", "visible": True, "size_bytes": 100, "modified_at": 1},
    {"name": "large.TIFF", "path": "large.TIFF", "kind": "raster", "visible": False, "size_bytes": 900, "modified_at": 2},
    {"name": "middle.tif", "path": "middle.tif", "kind": "raster", "visible": False, "size_bytes": 500, "modified_at": 3},
    {"name": "boundary.shp", "path": "boundary.shp", "kind": "vector", "visible": True, "size_bytes": 2000, "modified_at": 4},
]

# Evaluation labels are never supplied to the model.
CASES = [
    ("어떤 tif 용량이 가장 커?", "rows", ["large.TIFF"]),
    ("TIFF 중에서 제일 작은 파일의 이름과 크기 알려줘", "rows", ["small.tif"]),
    ("전체 파일 중 용량 큰 순서대로 두 개만 보여줘", "rows", ["boundary.shp", "large.TIFF"]),
    ("TIFF는 몇 개야?", "count", 3),
    ("숨겨진 TIFF 파일들의 총용량은?", "sum", 1400),
    ("숨긴 TIFF들의 평균 파일 크기를 계산해줘", "avg", 700),
    ("raster와 vector 종류별로 몇 개인지 나눠서 알려줘", "group", {"raster": 3, "vector": 1}),
    ("이름에 small이 들어간 레이어만 보여줘", "rows", ["small.tif"]),
    ("파일 크기가 1 KiB를 넘는 파일의 이름을 보여줘", "rows", ["boundary.shp"]),
    ("TIFF 해상도가 가장 높은 파일은?", "refuse", None),
    ("레이어를 삭제해줘", "refuse", None),
    ("가장 용량이 큰 파일이 뭐야?", "rows", ["boundary.shp"]),
    ("레이어 목록중에 두번째로 용량이 큰 파일이 뭐야?", "rows", ["large.TIFF"]),
    ("파일 크기로 내림차순 정렬해서 세 번째 파일 하나만 알려줘", "rows", ["middle.tif"]),
    ("용량 순서로 두 번째부터 두 개를 보여줘", "rows", ["large.TIFF", "middle.tif"]),
    ("레이어 목록에 대해 설명해줘", "rows", [row["name"] for row in ROWS]),
    ("레이어 목록과 포토샵 연결상태 확인해줘", "list_and_ping", [row["name"] for row in ROWS]),
    ("포토샵에 열려 있는 문서 목록 알려줘", "photoshop_read", "photoshop_list_documents"),
    ("포토샵 활성 문서 이름과 크기를 알려줘", "photoshop_read", "photoshop_get_document_info"),
    ("포토샵 문서의 레이어 목록 알려줘", "photoshop_read", "photoshop_get_layers"),
    ("현재 목록의 이미지 중 첫 번째 하나를 포토샵에 열어줘", "photoshop_open", ["small.tif"]),
]


class Desktop:
    def __init__(self):
        self.connections = {"evaluation": SimpleNamespace(connection_id="fixture")}
        self.next_document_id = 1
    async def call(self, client, body):
        if body.tool_name == "photoshop_ping":
            result = {"connected": True}
        elif body.tool_name == "photoshop_list_documents":
            result = {"documents": [{"id": 1, "name": "test.psd"}], "count": 1}
        elif body.tool_name == "photoshop_get_document_info":
            result = {"id": 1, "name": "test.psd", "width": 100, "height": 200}
        elif body.tool_name == "photoshop_get_layers":
            result = {"layers": [{"name": "Background"}], "layerCount": 1}
        elif body.tool_name == "photoshop_open_images":
            result = {"documents": [{"id": self.next_document_id + index, "name": path + " - AI", "source": path} for index, path in enumerate(body.arguments["paths"])], "failures": []}
            self.next_document_id += len(result["documents"])
        else:
            result = {"count": len(ROWS), "layers": [dict(row) for row in ROWS]}
        return ToolResult(call_id="fixture", status="succeeded", result=result)


async def evaluate(args):
    settings = Settings().model_copy(update={"ollama_model": args.model, "agent_mode": "general",
                                           "ollama_timeout_seconds": 15, "agent_timeout_seconds": 45})
    records = []
    async with httpx.AsyncClient(base_url=str(settings.ollama_base_url), timeout=15, trust_env=False) as http:
        state = SimpleNamespace(settings=settings, connections=Desktop(), ollama=OllamaClient(http, settings),
            registry=SimpleNamespace(get_tools=lambda _: SimpleNamespace(tools=[SimpleNamespace(name=name)
                for name in ("get_layer_list", "get_layer_metadata", "photoshop_ping", "photoshop_list_documents", "photoshop_get_document_info", "photoshop_get_layers", "photoshop_open_images")])))
        agent = GeneralAgent(set())
        for index, (question, expected_type, expected) in enumerate(CASES):
            if args.case_index is not None and index not in args.case_index:
                continue
            started = time.monotonic()
            record = {"question": question, "expected_type": expected_type, "passed": False}
            try:
                result = await agent.run(state, AgentChatRequest(client_id="evaluation", session_id=f"case-{index}",
                    messages=[{"role": "user", "content": question}]))
                data = result.query_result
                passed = False
                if expected_type == "photoshop_read":
                    passed = result.completion_status == "completed" and any(tool.tool_name == expected and tool.status == "succeeded" for tool in result.tool_results)
                elif expected_type == "photoshop_open":
                    opened = next((tool.result for tool in result.tool_results if tool.tool_name == "photoshop_open_images"), None)
                    passed = result.completion_status == "completed" and opened and [row["source"] for row in opened["documents"]] == expected
                elif expected_type == "refuse":
                    passed = data is None and result.completion_status != "completed"
                elif data and result.completion_status == "completed":
                    if expected_type in {"rows", "list_and_ping"}:
                        passed = data["aggregate"] is None and [row.get("name") for row in data["records"]] == expected
                        if expected_type == "list_and_ping":
                            passed = passed and any(tool.tool_name == "photoshop_ping" and tool.status == "succeeded" and tool.result.get("connected") is True for tool in result.tool_results)
                    elif expected_type == "group":
                        passed = data["aggregate"] and data["aggregate"]["function"] == "count" and {row["group"]: row["value"] for row in data["records"]} == expected
                    else:
                        passed = (data["aggregate"] and data["aggregate"]["function"] == expected_type
                                  and len(data["records"]) == 1 and data["records"][0]["value"] == expected)
                record.update(passed=bool(passed), warning=result.warning,
                              tools=[tool.tool_name for tool in result.tool_results],
                              message=result.message.content,
                              plan=data.get("plan") if data else None, actual=data.get("records") if data else None)
            except (OllamaError, ExecutionError) as exc:
                record["error"] = exc.code
                if exc.code in {"ollama_timeout", "agent_timeout"}:
                    record["seconds"] = round(time.monotonic() - started, 3)
                    records.append(record)
                    print(json.dumps(record, ensure_ascii=True), flush=True)
                    break  # Never stack more requests behind a timed-out generation.
            record["seconds"] = round(time.monotonic() - started, 3)
            records.append(record)
            print(json.dumps({key: record.get(key) for key in ("question", "passed", "warning", "error", "seconds")}, ensure_ascii=True), flush=True)
    report = {"model": args.model, "dataset": "synthetic_desktop", "suite": "development_not_independent_holdout", "passed": sum(row["passed"] for row in records),
              "tested": len(records), "total": len(CASES), "results": records}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RESULT {report['passed']}/{report['tested']} tested; total={report['total']} report={args.report}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--report", type=Path, default=Path("data/evaluations/general_agent.json"))
    parser.add_argument("--diagnostic-log", type=Path, help="Save rejected plans and reviews for debugging (may include filter values)")
    parser.add_argument("--case-index", type=int, action="append", help="Run selected zero-based development cases only")
    args = parser.parse_args()
    if args.diagnostic_log:
        args.diagnostic_log.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=args.diagnostic_log, encoding="utf-8", level=logging.INFO)
    asyncio.run(evaluate(args))
