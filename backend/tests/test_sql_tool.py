from datetime import date

import pytest
from app.agent.schemas import Filter, Period
from app.database import connection
from app.tools.sql import QuerySpec, compile_spec, display_sql, query_tool


def test_compile_spec_is_parameterised():
    sql, params = compile_spec(QuerySpec(metric="revenue", group_by=["region"],
                                         period=Period(label="2011-Q1", start=date(2011, 1, 1), end=date(2011, 4, 1))))
    assert "?" in sql and "2011" not in sql
    assert params == [date(2011, 1, 1), date(2011, 4, 1)]
    assert "'2011-01-01'" in display_sql(sql, ["2011-01-01", "2011-04-01"])


def test_query_tool_returns_rows_and_sql(fixture_db):
    r = query_tool(QuerySpec(metric="revenue", group_by=["region"]))
    assert r.ok and r.rows[0]["region"] == "United Kingdom"
    assert r.sql and r.sql[0].sql.startswith("SELECT")
    total = connection.execute("SELECT SUM(revenue) AS t FROM sales")["t"].iloc[0]
    assert abs(sum(x["revenue"] for x in r.rows) - total) < 0.01


def test_unknown_filter_value_is_rejected(fixture_db):
    r = query_tool(QuerySpec(metric="revenue", group_by=["region"], filters=[Filter(dimension="region", values=["Atlantis'; DROP TABLE sales;--"])]))
    assert not r.ok and "Unknown region" in r.error


def test_connection_is_read_only(fixture_db):
    with pytest.raises(connection.DatabaseError):
        connection.execute("CREATE TABLE hack AS SELECT 1")


def test_empty_result_is_no_answer(fixture_db):
    r = query_tool(QuerySpec(metric="revenue", group_by=["region"],
                             period=Period(label="2030", start=date(2030, 1, 1), end=date(2031, 1, 1))))
    assert not r.ok and r.no_answer
