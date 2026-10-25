import pytest
from app.tools.sql_safety import SQLValidationError, validate_sql

ALLOWED = [
    "SELECT region, SUM(revenue) AS r FROM sales GROUP BY region ORDER BY r DESC",
    "SELECT s.region, p.category, COUNT(*) AS n FROM sales s LEFT JOIN products p ON p.product_id = s.product_id GROUP BY 1, 2",
    "WITH t AS (SELECT region, revenue FROM sales) SELECT region, SUM(revenue) AS total FROM t GROUP BY region",
    "SELECT CAST(date_trunc('month', invoice_date) AS DATE) AS m, SUM(revenue) AS v FROM sales GROUP BY 1",
    "SELECT description FROM products WHERE description = 'DROP TABLE sales'",  # keyword inside a literal is fine
]
REJECTED = [
    ("DROP TABLE sales", "DROP"),
    ("DELETE FROM sales", "DELETE"),
    ("UPDATE sales SET revenue = 0", "UPDATE"),
    ("INSERT INTO sales VALUES (1)", "INSERT"),
    ("ALTER TABLE sales ADD COLUMN x INT", "ALTER"),
    ("TRUNCATE sales", "TRUNCATE"),
    ("CREATE TABLE x AS SELECT 1", "CREATE"),
    ("ATTACH 'other.db'", "ATTACH"),
    ("COPY sales TO 'out.csv'", "COPY"),
    ("PRAGMA database_list", "PRAGMA"),
    ("SELECT 1; SELECT 2", "Multiple"),
    ("SELECT region FROM sales; DROP TABLE sales", "Multiple"),
    ("SELECT * FROM read_csv('/etc/passwd')", "Table functions"),
    ("SELECT * FROM read_parquet('x.parquet')", "Table functions"),
    ("SELECT getenv('HOME')", "Function not allowed"),
    ("SELECT * FROM information_schema.tables", "Schema-qualified"),
    ("SELECT * FROM secrets", "Table not allowlisted"),
    ("SELECT password FROM sales", "Column not allowlisted"),
    ("SELECT region FROM sales UNION SELECT name FROM campaigns", "Only SELECT"),
    ("", "Empty"),
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed_queries_pass(sql):
    out = validate_sql(sql)
    assert out.upper().startswith(("SELECT", "WITH"))
    assert "LIMIT" in out.upper()


@pytest.mark.parametrize("sql,reason", REJECTED)
def test_dangerous_queries_rejected(sql, reason):
    with pytest.raises(SQLValidationError) as exc:
        validate_sql(sql)
    assert reason.lower() in str(exc.value).lower()


def test_limit_enforced_and_capped():
    assert "LIMIT 50" in validate_sql("SELECT region FROM sales", max_rows=50)
    assert "LIMIT 50" in validate_sql("SELECT region FROM sales LIMIT 100000", max_rows=50)
    assert "LIMIT 10" in validate_sql("SELECT region FROM sales LIMIT 10", max_rows=50)
