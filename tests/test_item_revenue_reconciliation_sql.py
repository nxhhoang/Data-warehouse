"""Execute the dbt item-revenue reconciliation with independent order fixtures."""
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _insert(connection, table, rows):
    columns = tuple(rows[0])
    names = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    connection.execute(f"CREATE TABLE {table} ({names})")
    connection.executemany(
        f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
        [tuple(row[column] for column in columns) for row in rows],
    )


def _source(event_id, revenue, price, quantity=1):
    return {"event_id": event_id, "event_name": "purchase",
            "quantity": quantity, "price_usd": price, "item_revenue_usd": revenue}


def _fact(user_key, transaction_id, revenue):
    return {"user_key": user_key, "transaction_id": transaction_id,
            "item_revenue_usd": revenue}


@pytest.fixture()
def reconciliation_rows():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    orders = [
        (1, "positive", 9.0),
        (2, "nonpositive", 8.0),
        (3, "wrong_revenue", 39.0),
        (4, "missing_source_row", 1.0),
        (5, "empty_source", 25.0),
        (6, "must_not_fabricate", 50.0),
    ]
    _insert(connection, "stg_valid_orders", [
        {"event_id": event_id, "user_pseudo_id": f"u{event_id}",
         "transaction_id": transaction_id, "revenue_usd": revenue}
        for event_id, transaction_id, revenue in orders
    ])
    _insert(connection, "dim_user", [
        {"user_pseudo_id": f"u{key}", "user_key": key} for key in range(1, 7)
    ])
    _insert(connection, "stg_ga4_items", [
        # Positive source revenue must be kept, rather than recomputed as price * qty.
        _source(1, 9.0, 3.0, 2),
        # Nonpositive source revenue takes the documented price * qty fallback.
        _source(2, -1.0, 4.0, 2),
        # A real source-to-fact discrepancy must be visible.
        _source(3, 20.0, 20.0),
        _source(3, 20.0, 20.0),
        # This source row exists but has no fact row, despite a tiny money gap.
        (_source(4, 0.0, 1.0)),
    ])
    _insert(connection, "fct_purchase_items", [
        _fact(1, "positive", 9.0),
        _fact(2, "nonpositive", 8.0),
        _fact(3, "wrong_revenue", 16.0),
        _fact(3, "wrong_revenue", 17.0),
        # No source row exists for transaction 6: inventing an item is forbidden.
        _fact(6, "must_not_fabricate", 50.0),
    ])
    yield connection
    connection.close()


def _real_reconciliation_sql():
    sql = (ROOT / "src" / "warehouse" / "tests" /
           "assert_item_revenue_reconciliation.sql").read_text(encoding="utf-8")
    # Only dbt's relation references need portability; the actual predicates remain.
    sql = re.sub(r"\{\{\s*ref\('([^']+)'\)\s*\}\}", lambda match: match.group(1), sql)
    assert "{{" not in sql
    return sql


def test_item_reconciliation_checks_lineage_and_unsupported_rows(reconciliation_rows):
    rows = reconciliation_rows.execute(_real_reconciliation_sql()).fetchall()
    assert sorted(row["transaction_id"] for row in rows) == [
        "missing_source_row", "must_not_fabricate", "wrong_revenue",
    ]
    assert {row["source_item_rows"] for row in rows} >= {0, 1, 2}
    assert all("order_vs_source_gap" in row.keys() for row in rows)
