import pytest

from app.agent.query_engine import FIELDS, Query, QueryError, execute, schema, select_positions

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


def test_generation_schema_separates_file_rows_from_aggregate_outputs():
    from jsonschema import Draft202012Validator
    validator = Draft202012Validator(schema(Query))
    ranked = query(select=["name", "size_bytes"], order_by=[{"field": "size_bytes", "direction": "desc"}], limit=1)
    assert validator.is_valid(ranked.model_dump())
    invalid = ranked.model_dump() | {"aggregate": {"function": "max", "field": "size_bytes"}}
    assert not validator.is_valid(invalid)
    scalar = query(select=["value"], aggregate={"function": "max", "field": "size_bytes"})
    assert validator.is_valid(scalar.model_dump())
    assert not validator.is_valid(scalar.model_dump() | {"select": ["name", "size_bytes"]})
    grouped = query(select=["group", "value"], group_by="extension", aggregate={"function": "count", "field": "*"})
    assert validator.is_valid(grouped.model_dump())


def test_ordinal_position_and_top_count_are_distinct_and_followups_use_returned_row():
    order = [{"field": "size_bytes", "direction": "desc"}]
    second = execute(query(order_by=order, offset=1, limit=1), ROWS, FIELDS)
    top_two = execute(query(order_by=order, offset=0, limit=2), ROWS, FIELDS)
    assert second["records"] == [{"name": "large.TIFF"}]
    assert top_two["records"] == [{"name": "boundary.shp"}, {"name": "large.TIFF"}]
    assert second["count"] == 4
    followup = execute(query(source="previous_result", aggregate={"function": "sum", "field": "size_bytes"}), second["rows"], FIELDS)
    assert followup["records"][0]["value"] == 900
    window = execute(query(order_by=order, offset=1, limit=2), ROWS, FIELDS)
    assert window["records"] == [{"name": "large.TIFF"}, {"name": "middle.tif"}]


def test_positions_are_applied_after_filtering_with_missing_size_notice_and_stable_ties():
    rows = [dict(row) for row in ROWS]
    rows[0]["size_bytes"] = None
    rows.append({**ROWS[1], "name": "tie.tiff"})
    result = execute(query(where=[TIFF], order_by=[{"field": "size_bytes", "direction": "desc"}], offset=1, limit=1), rows, FIELDS)
    assert result["records"] == [{"name": "tie.tiff"}]
    assert result["is_partial"] and result["excluded_count"] == 1
    assert execute(query(offset=1000), ROWS, FIELDS)["records"] == []
    with pytest.raises(QueryError):
        execute(query(offset=1, aggregate={"function": "count", "field": "*"}), ROWS, FIELDS)


@pytest.mark.parametrize("offset", [-1, 1001, True, 1.5])
def test_invalid_offsets_are_rejected(offset):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        query(offset=offset)


def test_noncontiguous_positions_preserve_order_deduplicate_and_reject_invalid_indices():
    assert select_positions(ROWS, [3, 1, 3]) == [ROWS[2], ROWS[0]]
    for numbers in ([], [0], [-1], [5], [1, True], [1, 9]):
        with pytest.raises(QueryError):
            select_positions(ROWS, numbers)
