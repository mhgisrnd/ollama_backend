from fastapi import APIRouter, Request

from app.schemas.registry import ClientId, ClientRecord, ClientRegistration, ToolCatalog, ToolRegistration

router = APIRouter(prefix="/api/v1/clients", tags=["clients & tools"])


@router.put("/{client_id}", response_model=ClientRecord, summary="벡터 프로그램 등록·갱신")
def register(client_id: ClientId, body: ClientRegistration, request: Request):
    """프로그램 설치별 고정 ID를 사용합니다. 재등록해도 기존 도구 목록은 유지됩니다.

    등록은 실행 중이거나 Photoshop에 연결되어 있음을 의미하지 않습니다.
    """
    return request.app.state.registry.register(client_id, body)


@router.get("", response_model=list[ClientRecord], summary="등록된 프로그램 목록")
def list_clients(request: Request):
    return request.app.state.registry.list_clients()


@router.put("/{client_id}/tools", response_model=ToolCatalog, summary="실행 가능 도구 목록 등록·교체")
def replace_tools(client_id: ClientId, body: ToolRegistration, request: Request):
    """먼저 프로그램을 등록하세요. 전송한 목록으로 전체 교체하며 빈 목록은 전체 해제입니다.

    이름·설명·입력 스키마의 형식만 검증합니다. 실제 실행·MCP 연결·LLM 도구 선택은 하지 않습니다.
    """
    return request.app.state.registry.replace_tools(client_id, body)


@router.get("/{client_id}/tools", response_model=ToolCatalog, summary="프로그램별 도구 목록 조회")
def get_tools(client_id: ClientId, request: Request):
    return request.app.state.registry.get_tools(client_id)
