"""Development evaluation of generic operations without editing .env or production data."""
import argparse
import asyncio
import json
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
]


class Desktop:
    def __init__(self):
        self.connections = {"evaluation": SimpleNamespace(connection_id="fixture")}
    async def call(self, client, body):
        if body.tool_name == "photoshop_ping":
            result = {"connected": True}
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
                for name in ("get_layer_list", "get_layer_metadata", "photoshop_ping")])))
        agent = GeneralAgent(set())
        for index, (question, expected_type, expected) in enumerate(CASES):
            started = time.monotonic()
            record = {"question": question, "expected_type": expected_type, "passed": False}
            try:
                result = await agent.run(state, AgentChatRequest(client_id="evaluation", session_id=f"case-{index}",
                    messages=[{"role": "user", "content": question}]))
                data = result.query_result
                passed = False
                if expected_type == "refuse":
                    passed = data is None and result.completion_status != "completed"
                elif data and result.completion_status == "completed":
                    if expected_type == "rows":
                        passed = data["aggregate"] is None and [row.get("name") for row in data["records"]] == expected
                    elif expected_type == "group":
                        passed = data["aggregate"] and data["aggregate"]["function"] == "count" and {row["group"]: row["value"] for row in data["records"]} == expected
                    else:
                        passed = (data["aggregate"] and data["aggregate"]["function"] == expected_type
                                  and len(data["records"]) == 1 and data["records"][0]["value"] == expected)
                record.update(passed=bool(passed), warning=result.warning,
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
    asyncio.run(evaluate(parser.parse_args()))
