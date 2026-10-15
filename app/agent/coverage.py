"""Conservative coverage checks for the two current read-only tools, not a general planner."""
import re

LABELS = {"get_layer_list": "레이어 조회", "photoshop_ping": "포토샵 연결 확인"}
MENTIONS = r"레이어|layers?|포토샵|photoshop"
NEGATIVE = re.compile(r"하지\s*마|하지\s*말|말고|제외|빼고|필요\s*없|하지\s*않|확인\s*말|don't|do not|without|skip", re.I)


def request_scope(messages):
    text = next((message.content for message in reversed(messages) if message.role == "user"), "").lower()
    requested, excluded = set(), set()
    if not re.search(r"알려|조회|확인|목록|개수|갯수|몇|상태|list|count|check|status", text):
        return requested, excluded
    matches = list(re.finditer(MENTIONS, text, re.I))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        clause = re.split(r"[,.!?;\n]", text[match.end():end], maxsplit=1)[0]
        tool = "get_layer_list" if re.fullmatch(r"레이어|layers?", match.group(), re.I) else "photoshop_ping"
        (excluded if NEGATIVE.search(clause) else requested).add(tool)
    # Contradictory requests are never expanded automatically.
    return requested - excluded, excluded


def factual_summary(trace, missing):
    parts = []
    for item in trace:
        if item.status != "succeeded":
            parts.append(f"{LABELS[item.tool_name]}: 확인 실패 또는 미실행입니다.")
        elif item.tool_name == "get_layer_list" and item.result:
            parts.append(f"현재 레이어는 총 {item.result.get('count', '확인 불가')}개입니다.")
        elif item.tool_name == "photoshop_ping" and item.result:
            parts.append("포토샵 통신에 성공했습니다." if item.result.get("connected") is True else "포토샵 통신 성공을 확인하지 못했습니다.")
    if missing:
        parts.append("미완료: " + ", ".join(LABELS[name] for name in missing) + ".")
    return " ".join(parts) or "요청한 기능이 실행되지 않아 현재 상태를 확인하지 못했습니다."
