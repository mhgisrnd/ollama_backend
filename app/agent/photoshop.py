"""Photoshop tool contracts and factual response formatting."""
READ_TOOLS = {"photoshop_list_documents", "photoshop_get_document_info", "photoshop_get_layers"}
OPEN_TOOL = "photoshop_open_images"
IMAGE_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".psd", ".psb", ".tga", ".webp", ".jp2", ".j2k"}


def describe(name, data):
    if data.get("has_document") is False:
        return "포토샵에 활성 문서가 없습니다."
    if name == OPEN_TOOL:
        documents, failures = data.get("documents", []), data.get("failures", [])
        text = f"새 포토샵 작업 탭 {len(documents)}개를 열었습니다." if documents else "이미지를 열지 못했습니다."
        if documents:
            if len(documents) > 3:
                text += "\n열린 문서 (앞 3개):"
            text += "\n" + "\n".join(str(row.get("name", "이름 없음")) for row in documents[:3])
            if len(documents) > 3:
                text += f"\n외 {len(documents) - 3}개도 열었습니다."
        if failures:
            text += f"\n※ {len(failures)}개 파일은 열지 못했습니다."
        return text
    if name == "photoshop_list_documents":
        rows = data.get("documents", [])
        return f"포토샵 문서 {len(rows)}개" + ("\n" + "\n".join(str(row.get("name", "이름 없음")) for row in rows[:3]) if rows else "입니다.")
    if name == "photoshop_get_layers":
        rows = data.get("layers", [])
        return f"포토샵 레이어 {data.get('layerCount', len(rows))}개" + ("\n" + "\n".join(str(row.get("name", "이름 없음")) for row in rows[:3]) if rows else "입니다.")
    return f"활성 문서: {data.get('name', '이름 확인 불가')}\n크기: {data.get('width', '?')} × {data.get('height', '?')} px"
