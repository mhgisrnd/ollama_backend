import pytest

from app.agent.query_constraints import enforce_explicit_scope
from test_query_engine import query


@pytest.mark.parametrize("text", ["숨겨진 shp만 알려줘", "표시된 tif 이름", "표시 여부도 알려줘", "전체 ecw 이름"])
def test_other_visibility_requests_keep_their_filters(text):
    candidate = query(where=[{"field": "visible", "operator": "eq", "values": ["false"]}])
    assert enforce_explicit_scope(candidate, text) == candidate


@pytest.mark.parametrize("text", ["표시 여부는 상관없어", "표시 여부와 관계없이", "표시여부 무관", "표시 여부와 상관없이"])
def test_unrestricted_visibility_preserves_other_constraints_and_input(text):
    candidate = query(where=[
        {"field": "extension", "operator": "in", "values": [".tif", ".tiff"]},
        {"field": "visible", "operator": "ne", "values": ["true"]},
    ], source="current", select=["name"])
    normalized = enforce_explicit_scope(candidate, text)
    assert normalized.where == candidate.where[:1]
    assert len(candidate.where) == 2
    assert normalized.source == "current" and normalized.select == ["name"]
