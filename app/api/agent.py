from fastapi import APIRouter, Request

from app.schemas.agent import AgentChatRequest, AgentChatResponse

router = APIRouter(prefix="/api/v1/agent", tags=["AI agent"])


@router.post("/chat", response_model=AgentChatResponse, summary="자연어로 레이어 조회·Photoshop 연결 확인")
async def agent_chat(body: AgentChatRequest, request: Request):
    """연결된 client_id가 필요합니다. LLM이 도구를 선택하며 실제 결과는 tool_results에서 확인합니다.

    편집 기능과 대화 저장은 제공하지 않습니다. 이전 대화는 messages에 함께 전달하세요.
    """
    return await request.app.state.agent.run(request.app.state, body)
