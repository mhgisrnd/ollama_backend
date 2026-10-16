"""Real Ollama, synthetic desktop: displayed numbers must resolve to exact files."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.agent.general import GeneralAgent
from app.core.config import Settings
from app.llm.ollama import OllamaClient
from app.schemas.agent import AgentChatRequest
from app.schemas.execution import ToolResult
from app.experiments.evaluate_general_agent import Desktop


class NumberedDesktop(Desktop):
    def __init__(self):
        super().__init__()
        self.opens = []
        self.rows = [{"name": f"image-{i}.png", "path": f"image-{i}.png", "kind": "raster", "visible": True}
                     for i in range(1, 7)] + [{"name": "boundary.shp", "path": "boundary.shp", "kind": "vector", "visible": True}]

    async def call(self, client, body):
        if body.tool_name in {"get_layer_list", "get_layer_metadata"}:
            return ToolResult(call_id="fixture", status="succeeded", result={"layers": self.rows, "count": len(self.rows)})
        if body.tool_name == "photoshop_open_images":
            self.opens.append(body.arguments["paths"])
        return await super().call(client, body)


async def evaluate(args):
    settings = Settings().model_copy(update={"ollama_model": args.model, "agent_mode": "general", "ollama_timeout_seconds": 30, "agent_timeout_seconds": 60})
    desktop, agent, records = NumberedDesktop(), GeneralAgent(set()), []
    names = ["get_layer_list", "get_layer_metadata", "photoshop_ping", "photoshop_open_images"]
    async with httpx.AsyncClient(base_url=str(settings.ollama_base_url), timeout=30, trust_env=False) as http:
        state = SimpleNamespace(settings=settings, connections=desktop, ollama=OllamaClient(http, settings),
            registry=SimpleNamespace(get_tools=lambda _: SimpleNamespace(tools=[SimpleNamespace(name=name) for name in names])))
        cases = [("현재 레이어 목록을 알려줘", None), ("1,2,4,5,6번 파일 열어줘", ["image-1.png", "image-2.png", "image-4.png", "image-5.png", "image-6.png"]),
                 ("7번 파일 열어줘", []), ("99번 파일 열어줘", []), ("0번 파일 열어줘", [])]
        reference_id = None
        for question, expected in cases:
            before = len(desktop.opens)
            result = await agent.run(state, AgentChatRequest(client_id="evaluation", session_id="numbered-workflow", reference_id=reference_id,
                messages=[{"role": "user", "content": question}]))
            if expected is None:
                passed = bool(result.query_result and [row.get("number") for row in result.query_result["records"]] == list(range(1, 8)))
            elif expected:
                passed = desktop.opens[before:] == [expected] and result.completion_status == "completed"
            else:
                passed = (len(desktop.opens) == before and result.completion_status == "failed"
                          and ("이미지가 아닌" in result.message.content if question.startswith("7번") else "1~7" in result.message.content))
            if result.query_result:
                reference_id = result.query_result.get("reference_id", reference_id)
            records.append({"question": question, "passed": passed, "message": result.message.content,
                            "layer_query_count": sum(tool.tool_name == "query_layers" for tool in result.tool_results),
                            "opened": desktop.opens[before:], "status": result.completion_status})
            print(json.dumps(records[-1], ensure_ascii=True), flush=True)
            if expected is None and not passed:
                break
    report = {"model": args.model, "suite": "development_synthetic_desktop_no_real_photoshop", "passed": sum(record["passed"] for record in records), "tested": len(records), "results": records}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"RESULT {report['passed']}/{report['tested']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:4b-instruct")
    parser.add_argument("--report", type=Path, default=Path("data/evaluations/numbered_images.json"))
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=args.report.with_suffix(".log"), encoding="utf-8", level=logging.INFO)
    asyncio.run(evaluate(args))
