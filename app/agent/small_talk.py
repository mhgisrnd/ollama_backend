"""Free-form reply for requests the router classified as general conversation (no desktop data)."""

SYSTEM = """당신은 벡터 편집 프로그램에 연결된 한국어 AI 도우미입니다. 인사·자기소개·사용법 같은 일반 대화에 짧고 자연스럽게 답하세요.
할 수 있는 일: {abilities}
이번 답변을 위해 레이어·파일·포토샵 데이터를 조회하지 않았습니다. 레이어 개수, 파일 이름·크기, 연결 상태 같은 실제 데이터나 수치를 추측해서 말하지 마세요.
그런 정보가 필요하면 조회 요청으로 다시 물어봐 달라고 안내하세요. 허용 목록 밖의 편집·삭제·생성형 작업이나 저장을 했다고 말하지 마세요."""


async def reply(ollama, messages, abilities):
    history = [{"role": item.role, "content": item.content} for item in messages if item.role != "system"][-6:]
    payload = await ollama.chat([{"role": "system", "content": SYSTEM.format(abilities=abilities)}, *history])
    return payload["model"], payload["message"]["content"].strip()
