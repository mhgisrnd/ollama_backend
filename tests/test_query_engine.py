import pytest

from app.agent.query_engine import FIELDS, Query, QueryError, execute

ROWS = [
    {"name": "small.tif", "kind": "raster", "path": "small.tif", "visible": True, "size_bytes": 100, "modified_at": 1},
    {"name": "large.TIFF", "kind": "raster", "path": "large.TIFF", "visible": False, "size_bytes": 900, "modified_at": 2},
    {"name": "middle.tif", "kind": "raster", "path": "middle.tif", "visible": False, "size_bytes": 500, "modified_at": 3},
    {"name": "boundary.shp", "kind": "vector", "path": "boundary.shp", "visible": True, "size_bytes": 2000, "modified_at": 4},
]
TIFF = {"field": "extension", "operator": "in", "values": [".tif", ".tiff"]}


def query(**values):
    return Query.model_validate({"source": "current", "where": [], "select": ["name"],
        "order_by": [], "limit": 1000, "aggregate": None, "group_by": None} | values)


def test_largest_and_top_n_are_composed_from_filter_sort_and_limit():
    result = execute(query(where=[TIFF], select=["name", "size_bytes"],
                     order_by=[{"field": "size_bytes", "direction": "desc"}], limit=1), ROWS, FIELDS)
    assert result["records"] == [{"name": "large.TIFF", "size_bytes": 900}]
    assert result["count"] == 3 and result["truncated"]


@pytest.mark.parametrize("function, expected", [("sum", 1400), ("avg", 700), ("min", 500), ("max", 900)])
def test_numeric_aggregates_after_multiple_filters(function, expected):
    result = execute(query(where=[TIFF, {"field": "visible", "operator": "eq", "values": ["false"]}],
        aggregate={"function": function, "field": "size_bytes"}), ROWS, FIELDS)
    assert result["records"] == [{"group": None, "value": expected}]


def test_group_count_name_filter_and_size_units():
    grouped = execute(query(aggregate={"function": "count", "field": "*"}, group_by="kind"), ROWS, FIELDS)
    assert grouped["records"] == [{"group": "raster", "value": 3}, {"group": "vector", "value": 1}]
    result = execute(query(where=[{"field": "name", "operator": "contains", "values": ["large"]},
        {"field": "size_bytes", "operator": "gt", "values": ["0.5 KiB"]}]), ROWS, FIELDS)
    assert result["count"] == 1


def test_unknown_fields_are_not_silently_replaced_with_counts():
    with pytest.raises(QueryError, match="resolution"):
        execute(query(select=["resolution"]), ROWS, FIELDS)
    with pytest.raises(QueryError, match="size_bytes"):
        execute(query(select=["size_bytes"]), ROWS, {"name"})


def test_unknown_file_size_cannot_establish_a_maximum_or_total():
    rows = [dict(row) for row in ROWS]
    rows[0]["size_bytes"] = None
    ranked = execute(query(where=[TIFF], order_by=[{"field": "size_bytes", "direction": "desc"}], limit=1), rows, FIELDS)
    assert ranked["records"] == [{"name": "large.TIFF"}]
    total = execute(query(aggregate={"function": "sum", "field": "size_bytes"}), rows, FIELDS)
    assert total["records"][0]["value"] == 3400
    for result in (ranked, total):
        assert result["is_partial"] and result["excluded_count"] == 1
        assert "전체 대상" in result["warnings"][0]
    # Missing file sizes do not prevent an unrelated count.
    assert execute(query(aggregate={"function": "count", "field": "*"}), rows, FIELDS)["records"][0]["value"] == 4


def test_list_preserves_rows_with_missing_display_fields():
    rows = [dict(row) for row in ROWS] + [{"name": "temporary", "kind": "vector", "visible": True}]
    result = execute(query(select=["name", "path", "size_bytes"]), rows, FIELDS)
    assert result["count"] == 5 and len(result["records"]) == 5
    assert result["records"][-1] == {"name": "temporary", "path": None, "size_bytes": None}
    assert not result["is_partial"] and result["excluded_count"] == 0
    assert result["warnings"]


def test_missing_filter_data_and_all_missing_sum_are_explicit():
    rows = [{"name": "temporary", "size_bytes": None}]
    result = execute(query(where=[{"field": "size_bytes", "operator": "gt", "values": ["1 KiB"]}]), rows, FIELDS)
    assert result["is_partial"] and result["count"] == 0
    result = execute(query(aggregate={"function": "sum", "field": "size_bytes"}), rows, FIELDS)
    assert result["records"][0]["value"] is None and result["is_partial"]


def test_followup_preserves_top_n_rows_and_source_data_is_not_mutated():
    first = execute(query(order_by=[{"field": "size_bytes", "direction": "desc"}], limit=2), ROWS, FIELDS)
    followup = execute(query(source="previous_result", aggregate={"function": "sum", "field": "size_bytes"}), first["rows"], FIELDS)
    assert followup["records"][0]["value"] == 2900
    assert ROWS[0]["name"] == "small.tif"


def test_empty_aggregates_and_invalid_types_are_explicit():
    assert execute(query(aggregate={"function": "count", "field": "*"}), [], FIELDS)["records"][0]["value"] == 0
    assert execute(query(aggregate={"function": "avg", "field": "size_bytes"}), [], FIELDS)["records"][0]["value"] is None
    with pytest.raises(QueryError):
        execute(query(where=[{"field": "visible", "operator": "eq", "values": ["maybe"]}]), ROWS, FIELDS)
    with pytest.raises(QueryError):
        execute(query(where=[{"field": "extension", "operator": "gt", "values": ["tif", "shp"]}]), ROWS, FIELDS)
