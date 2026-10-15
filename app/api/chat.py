from uuid import uuid4

from fastapi import APIRouter, Request

from app.schemas.chat import ChatRequest, ChatResponse, ChatMessage

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, summary="Ollama 기본 채팅")
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    """대화 이력을 매번 전달합니다. 서버에 대화를 저장하지 않으며 도구를 실행하지 않습니다."""
    payload = await request.app.state.ollama.chat([message.model_dump() for message in body.messages])
    return ChatResponse(
        request_id=str(uuid4()),
        model=payload["model"],
        message=ChatMessage(role="assistant", content=payload["message"]["content"]),
        done_reason=payload.get("done_reason"),
    )
