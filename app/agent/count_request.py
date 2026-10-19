"""Conservatively expand shorthand counts without dropping unknown constraints."""
import re


_FORMAT = r"\.? (?:tiff?|shp|dxf|ecw)".replace(" ", "")
_REQUEST = re.compile(
    rf"\s*(?:지금\s*|현재\s*)?(?P<formats>{_FORMAT}(?:\s*(?:와|과|랑|이랑|하고|및|,|/|&)\s*{_FORMAT})+)"
    r"\s*(?:레이어\s*)?(?P<total>합쳐서\s*|합해서\s*|합계\s*|총\s*)?"
    r"(?:각각\s*|각\s*)?(?:개수|갯수|몇\s*개)(?:가|는|를|야|인가요|인지)?"
    r"\s*(?:궁금해요?|알려\s*줘요?|알려주세요|있어|있나요)?\s*[?!.]*\s*",
    re.IGNORECASE,
)


def expand_count_request(text: str) -> str:
    match = _REQUEST.fullmatch(text)
    if not match:
        return text
    formats = list(dict.fromkeys(
        "TIFF" if value.lower().lstrip(".") in {"tif", "tiff"} else value.upper().lstrip(".")
        for value in re.findall(_FORMAT, match["formats"], re.IGNORECASE)
    ))
    if len(formats) < 2:
        return text
    names = ", ".join(formats)
    if match["total"]:
        return f"현재 전체 레이어에서 {names} 형식에 해당하는 레이어 개수의 합계를 하나의 값으로 알려줘."
    return f"현재 전체 레이어에서 {names} 형식별 레이어 개수를 각각 알려줘. TIFF는 .tif와 .tiff를 합친 개수야."
