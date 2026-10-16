"""Real Ollama + production agent + synthetic desktop. Never modifies application data."""
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.agent.layer_query import LayerQuery, QuerySession
from app.agent.runner import AgentRunner
from app.core.config import Settings
from app.experiments.evaluate_layer_query import CASES, FIXTURE
from app.llm.ollama import OllamaClient
from app.schemas.agent import AgentChatRequest
from app.schemas.execution import ToolResult


class SyntheticDesktop:
    def __init__(self):
        self.connections = {"evaluation": SimpleNamespace(connection_id="evaluation")}
        self.rows = FIXTURE
        self.calls = []

    async def call(self, client_id, request):
        self.calls.append(request.tool_name)
        data = ({"count": len(self.rows), "layers": self.rows} if request.tool_name == "get_layer_list"
                else {"connected": True})
        return ToolResult(call_id="evaluation", status="succeeded", result=data)


async def main():
    settings = Settings().model_copy(update={"agent_mode": "structured"})
    desktop = SyntheticDesktop()
    async with httpx.AsyncClient(base_url=str(settings.ollama_base_url), timeout=25, trust_env=False) as http:
        state = SimpleNamespace(settings=settings, connections=desktop,
            registry=SimpleNamespace(get_tools=lambda _: SimpleNamespace(tools=[SimpleNamespace(name=name)
                for name in ("get_layer_list", "photoshop_ping")])), ollama=OllamaClient(http, settings))
        agent, records = AgentRunner(), []
        for repeat in range(2):
            oracle = QuerySession()
            for index, (question, expected) in enumerate(CASES):
                desktop.rows = FIXTURE + ([{"name": "new.tif", "visible": True}] if index == 4 else [])
                target = oracle.execute(LayerQuery.model_validate(expected), lambda: desktop.rows)
                started = time.monotonic()
                result = await agent.run(state, AgentChatRequest(client_id="evaluation", session_id=f"run-{repeat}",
                                             messages=[{"role": "user", "content": question}]))
                computed = result.query_result
                record = {"repeat": repeat + 1, "turn": index + 1, "seconds": round(time.monotonic() - started, 3),
                          "status": result.completion_status, "warning": result.warning,
                          "count": computed["count"] if computed else None,
                          "query": computed["query"] if computed else None,
                          "passed": bool(computed and computed["count"] == target["count"]
                              and computed["query"]["source"] == expected["source"]
                              and computed["query"]["output"] == expected["output"]
                              and sorted(computed["names"]) == sorted(target["names"]))}
                records.append(record)
                print(json.dumps(record, ensure_ascii=True), flush=True)
        for index, (question, expected_count) in enumerate([
            ("현재 레이어 목록은 어떻고 그중 tif는 몇개인지 알려줘", 3),
            ("전체 레이어 목록과 그중 TIFF 개수를 한 번에 알려줘", 3),
            ("지금 레이어 목록 보여주고 그중 SHP 개수도 알려줘", 2),
        ]):
            desktop.rows = FIXTURE
            first_call = len(desktop.calls)
            started = time.monotonic()
            result = await agent.run(state, AgentChatRequest(client_id="evaluation", session_id=f"compound-{index}",
                                         messages=[{"role": "user", "content": question}]))
            queries = [item.result for item in result.tool_results if item.tool_name == "query_layers" and item.status == "succeeded"]
            # A current query over the shared full snapshot is set-equivalent
            # to previous_result when the first stage is the unfiltered full list.
            passed = (len(queries) == 2 and queries[0]["count"] == 6 and queries[1]["count"] == expected_count
                      and queries[0]["query"]["source"] == "current" and queries[0]["query"]["output"] == "list"
                      and queries[0]["query"]["filters"] == {"extensions": [], "visible": None}
                      and queries[1]["query"]["output"] == "count"
                      and desktop.calls[first_call:] == ["get_layer_list"])
            record = {"scenario": "compound_first_turn", "question": question, "passed": passed,
                      "seconds": round(time.monotonic() - started, 3), "status": result.completion_status,
                      "warning": result.warning, "queries": [item["query"] for item in queries],
                      "counts": [item["count"] for item in queries]}
            records.append(record)
            print(json.dumps(record, ensure_ascii=True), flush=True)
        report = {"model": settings.ollama_model, "dataset": "synthetic_desktop",
                  "passed": sum(row["passed"] for row in records), "total": len(records), "results": records}
        path = Path("data/evaluations/structured_agent.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"RESULT {report['passed']}/{report['total']} report={path}")


if __name__ == "__main__":
    asyncio.run(main())
