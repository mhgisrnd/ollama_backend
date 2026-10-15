from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/ollama", tags=["ollama"])


class OllamaStatus(BaseModel):
    connected: bool
    version: str
    configured_model: str
    model_available: bool
    models: list[str]


@router.get("/status", response_model=OllamaStatus, summary="Ollama 연결·모델 확인")
async def status(request: Request):
    """버전과 설치 모델 목록을 조회합니다. 추론이나 모델 다운로드는 실행하지 않습니다."""
    return await request.app.state.ollama.status()
