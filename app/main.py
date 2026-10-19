from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router
from app.core.config import Settings
from app.api.chat import router as chat_router
from app.api.ollama import router as ollama_router
from app.llm.ollama import OllamaClient, OllamaError
from app.api.clients import router as clients_router
from app.core.config import PROJECT_ROOT
from app.storage.registry import ClientNotFound, RegistryStore
from app.execution.connections import ConnectionManager, ExecutionError
from app.api.execution import router as execution_router
from app.agent.runner import AgentRunner
from app.api.agent import router as agent_router
from app.agent.cancellation import AgentRequests


def create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings()
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database_path = settings.registry_database_path
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path
        application.state.registry = RegistryStore(database_path)
        application.state.registry.initialize()
        async with httpx.AsyncClient(
            base_url=str(settings.ollama_base_url).rstrip("/") + "/",
            timeout=settings.ollama_timeout_seconds,
            trust_env=False,
            transport=transport,
        ) as http:
            application.state.ollama = OllamaClient(http, settings)
            yield

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Spatial editor AI backend - Ollama tool calling with read-only desktop tools.",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.connections = ConnectionManager()
    application.state.agent = AgentRunner()
    application.state.agent_requests = AgentRequests()
    application.include_router(router)
    application.include_router(ollama_router)
    application.include_router(chat_router)
    application.include_router(clients_router)
    application.include_router(execution_router)
    application.include_router(agent_router)

    @application.exception_handler(ExecutionError)
    async def execution_error_handler(request: Request, exc: ExecutionError):
        return JSONResponse(status_code=exc.status, content={"detail": {
            "code": exc.code, "message": exc.message, "call_id": exc.call_id,
        }})

    @application.exception_handler(ClientNotFound)
    async def client_not_found_handler(request: Request, exc: ClientNotFound):
        return JSONResponse(status_code=404, content={"detail": {
            "code": "client_not_found", "message": "등록되지 않은 프로그램입니다. 먼저 클라이언트를 등록하세요.",
        }})

    @application.exception_handler(OllamaError)
    async def ollama_error_handler(request: Request, exc: OllamaError):
        return JSONResponse(status_code=exc.status, content={"detail": {"code": exc.code, "message": exc.message}})

    return application


app = create_app()
