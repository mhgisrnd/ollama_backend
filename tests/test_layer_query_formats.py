import pytest
from jsonschema import Draft202012Validator

from app.agent.layer_query import LayerQuery, QuerySession, inline_schema


@pytest.mark.parametrize("extension", [".dxf", ".ecw"])
def test_cad_and_raster_formats_support_count_and_hidden_followup(extension):
    rows = [
        {"name": "visible", "path": "C:\\maps\\visible" + extension.upper(), "visible": True},
        {"name": "hidden" + extension, "visible": False},
        {"name": "other.tif", "visible": True},
    ]
    arguments = {"source": "current", "filters": {"extensions": [extension], "visible": None}, "output": "count"}
    Draft202012Validator(inline_schema()).validate(arguments)
    session = QuerySession()
    assert session.execute(LayerQuery.model_validate(arguments), lambda: rows)["count"] == 2
    followup = LayerQuery.model_validate({
        "source": "previous_result", "filters": {"extensions": [extension], "visible": False}, "output": "list",
    })
    result = session.execute(followup, lambda: pytest.fail("Follow-up should use previous rows"))
    assert result["count"] == 1
    assert result["names"] == ["hidden" + extension]
