import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.experiments.layer_query import LayerQuery, QuerySession, inline_schema
from app.experiments.evaluate_layer_query import CASES, FIXTURE


def test_followup_filters_count_keeps_rows_and_refreshes_provider():
    session = QuerySession()
    reads = []
    rows = list(FIXTURE)
    def current():
        reads.append(True)
        return rows
    counts = []
    for index, (_, arguments) in enumerate(CASES):
        if index == 4:
            rows.append({"name": "fresh.tif", "visible": True})
        result = session.execute(LayerQuery.model_validate(arguments), current)
        counts.append(result["count"])
    assert counts == [6, 3, 2, 2, 7]
    assert len(reads) == 3


def test_sessions_are_isolated_and_no_history_does_not_fallback_to_all():
    first, second = QuerySession(), QuerySession()
    first.execute(LayerQuery.model_validate(CASES[0][1]), lambda: FIXTURE)
    with pytest.raises(ValueError, match="No previous result"):
        second.execute(LayerQuery.model_validate(CASES[1][1]), lambda: FIXTURE)
    assert second.context()["previous_result_available"] is False


@pytest.mark.parametrize("update", [
    {"source": "eval"}, {"output": "delete"}, {"code": "print(1)"},
    {"filters": {"extensions": [".exe"], "visible": None}},
    {"filters": {"extensions": [], "visible": "false"}},
])
def test_unknown_operations_and_invalid_conditions_are_rejected(update):
    with pytest.raises(ValidationError):
        LayerQuery.model_validate(CASES[0][1] | update)


def test_schema_is_inline_and_executor_does_not_modify_input():
    schema = inline_schema()
    Draft202012Validator.check_schema(schema)
    assert "$ref" not in str(schema)
    rows = [dict(row) for row in FIXTURE]
    before = [dict(row) for row in rows]
    session = QuerySession()
    session.execute(LayerQuery.model_validate(CASES[0][1]), lambda: rows)
    session.previous_rows[0]["name"] = "changed"
    assert rows == before
