"""SQL safety layer: only a single, allowlisted, read-only SELECT may run."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from app.database.schema import ALL_COLUMNS, ALLOWED_SCHEMA

FORBIDDEN_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|ATTACH|DETACH|COPY|PRAGMA|INSTALL|LOAD|EXPORT|"
    r"IMPORT|SET|RESET|CALL|GRANT|REVOKE|VACUUM|CHECKPOINT|MERGE|REPLACE|USE|EXECUTE|PREPARE)\b",
    re.IGNORECASE,
)
FORBIDDEN_FUNCTION = re.compile(
    r"^(read_|glob|sniff_|parquet_|getenv|current_setting|pg_|duckdb_|query|system|sql_|"
    r"httpfs|http_|load|install|from_json|json_execute|iceberg|delta_|sqlite_|postgres_|mysql_)",
    re.IGNORECASE,
)
FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create, exp.Command,
                   exp.Merge, exp.Use, exp.Set, exp.Pragma, exp.TruncateTable, exp.Copy)


class SQLValidationError(ValueError):
    pass


def _strip_literals(sql: str) -> str:
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)


def validate_sql(sql: str, max_rows: int = 500) -> str:
    """Return a normalised, LIMIT-enforced SELECT or raise SQLValidationError."""
    if not sql or not sql.strip():
        raise SQLValidationError("Empty SQL.")
    if len(sql) > 5000:
        raise SQLValidationError("SQL is too long.")
    stripped = _strip_literals(sql)
    if ";" in stripped.strip().rstrip(";"):
        raise SQLValidationError("Multiple statements are not allowed.")
    match = FORBIDDEN_KEYWORDS.search(stripped)
    if match:
        raise SQLValidationError(f"Forbidden keyword: {match.group(1).upper()}.")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise SQLValidationError("SQL could not be parsed.") from exc
    if len(statements) != 1:
        raise SQLValidationError("Exactly one statement is required.")
    stmt = statements[0]
    if not isinstance(stmt, exp.Select):
        raise SQLValidationError("Only SELECT statements are allowed.")
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SQLValidationError(f"Forbidden operation: {type(node).__name__}.")

    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        if table.args.get("db") or table.args.get("catalog"):
            raise SQLValidationError("Schema-qualified tables are not allowed.")
        if not isinstance(table.this, exp.Identifier):
            raise SQLValidationError("Table functions are not allowed.")
        name = table.name.lower()
        if name not in ALLOWED_SCHEMA and name not in cte_names:
            raise SQLValidationError(f"Table not allowlisted: {name}.")

    for func in stmt.find_all(exp.Func):
        name = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
        if FORBIDDEN_FUNCTION.match(name or ""):
            raise SQLValidationError(f"Function not allowed: {name}.")

    aliases = {a.alias.lower() for a in stmt.find_all(exp.Alias)}
    aliases |= {t.alias.lower() for t in stmt.find_all(exp.Table) if t.alias}
    aliases |= {s.alias.lower() for s in stmt.find_all(exp.Subquery) if s.alias}
    for col in stmt.find_all(exp.Column):
        name = col.name.lower()
        if isinstance(col.this, exp.Star):
            continue
        if name not in ALL_COLUMNS and name not in aliases:
            raise SQLValidationError(f"Column not allowlisted: {name}.")

    limit = stmt.args.get("limit")
    if limit is None:
        stmt = stmt.limit(max_rows)
    else:
        try:
            value = int(limit.expression.this)
        except (AttributeError, TypeError, ValueError) as exc:
            raise SQLValidationError("LIMIT must be a constant integer.") from exc
        if value > max_rows:
            stmt = stmt.limit(max_rows)
    return stmt.sql(dialect="duckdb", pretty=True)
