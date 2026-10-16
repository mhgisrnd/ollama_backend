from fastapi import APIRouter, Request

from app.schemas.agent import AgentChatRequest, AgentChatResponse

router = APIRouter(prefix="/api/v1/agent", tags=["AI agent"])


@router.post("/chat", response_model=AgentChatResponse, summary="자연어로 레이어 조회·Photoshop 연결 확인")
async def agent_chat(body: AgentChatRequest, request: Request):
    """연결된 client_id가 필요합니다. LLM이 도구를 선택하며 실제 결과는 tool_results에서 확인합니다.

    기본 structured 모드에서는 session_id별 직전 조회 결과를 메모리에 보관합니다.
    후속 질문은 같은 session_id를 사용하고 새 대화는 새 ID를 사용하세요.
    서버 재시작·연결 변경·30분 경과 시 결과가 만료됩니다. session_id 생략 시 단일 요청으로 처리합니다.
    편집 및 대화 영구 저장은 제공하지 않습니다. 계산 결과는 query_result에서 확인하세요.
    """
    return await request.app.state.agent.run(request.app.state, body)
