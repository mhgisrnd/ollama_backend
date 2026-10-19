import pytest

from app.agent.count_request import expand_count_request


@pytest.mark.parametrize("text", ["tif와 shp 개수가 궁금해", "DXF랑 ECW 몇개야?", ".tif, .shp 개수", "현재 tif하고 shp 개수 알려줘"])
def test_short_counts_mean_separate_format_counts(text):
    assert "각각" in expand_count_request(text)


@pytest.mark.parametrize("text", ["tif와 shp 합쳐서 몇 개야?", "tif랑 shp 총 개수 알려줘"])
def test_explicit_total_is_preserved(text):
    assert "합계" in expand_count_request(text)
    assert "각각" not in expand_count_request(text)


@pytest.mark.parametrize("text", [
    "숨겨진 tif와 shp 개수", "그중 tif와 shp 개수", "tif와 shp 개수와 포토샵 연결 상태",
    "tif와 shp 삭제해줘", "tif와 shp 중 100MB 이상 개수", "tif와 shp 이름 목록",
    "tif와 tiff 개수", "tif 개수", "tif와 shp 개수 제외하고 ecw 알려줘",
])
def test_unknown_constraints_and_other_operations_are_not_rewritten(text):
    assert expand_count_request(text) == text
