"""Execute the report's KPI SQL views against small, hand-calculated fixtures.

SQLite runs the actual SELECT statements from src/kpi. Only the CREATE VIEW
portability wrapper and SAFE_DIVIDE are shimmed; no KPI formula is copied into
this test. BigQuery Sandbox integration remains a separate validation step.
"""
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _safe_divide(numerator, denominator):
    """Match BigQuery's zero-denominator behavior for numeric arguments."""
    if numerator is None or denominator in (None, 0, 0.0):
        return None
    return numerator / denominator


def _insert_rows(connection, table, rows):
    columns = tuple(rows[0])
    names = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    connection.execute(f"CREATE TABLE {table} ({names})")
    connection.executemany(
        f"INSERT INTO {table} ({names}) VALUES ({placeholders})",
        [tuple(row[column] for column in columns) for row in rows],
    )


def _mart(date_key, source_key, device_key, **values):
    """One aggregate input row, with zero for unspecified fact measures."""
    row = {name: 0 for name in (
        "sessions", "engaged_sessions", "page_views", "engagement_time_msec",
        "view_item_events", "sessions_with_view_item", "sessions_with_add_to_cart",
        "sessions_with_begin_checkout", "sessions_with_add_shipping_info",
        "sessions_with_add_payment_info", "sessions_with_purchase",
        "sessions_cart_and_purchase", "sessions_checkout_and_purchase",
        "sessions_payment_and_purchase", "orders", "revenue_usd",
    )}
    row.update(date_key=date_key, session_source_key=source_key, device_key=device_key)
    row.update(values)
    return row


def _session(session_id, user_key, date_key, source_key, device_key):
    return {
        "session_id": session_id, "user_key": user_key, "date_key": date_key,
        "session_source_key": source_key, "device_key": device_key,
    }


@pytest.fixture(scope="module")
def database():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.create_function("SAFE_DIVIDE", 2, _safe_divide)
    tables = {
        "dim_date": [
            {"date_key": 20201218, "full_date": "2020-12-18", "year_month": "202012",
             "is_weekend": False, "is_add_to_cart_tracked": True},
            {"date_key": 20201219, "full_date": "2020-12-19", "year_month": "202012",
             "is_weekend": True, "is_add_to_cart_tracked": False},
        ],
        "dim_traffic_source": [
            {"traffic_source_key": 1, "channel_group": "Organic Search", "source": "google",
             "medium": "organic", "campaign": "launch", "is_unassigned": False},
            {"traffic_source_key": 2, "channel_group": "Direct", "source": "direct",
             "medium": "(none)", "campaign": "default", "is_unassigned": False},
            {"traffic_source_key": 3, "channel_group": "Email", "source": "newsletter",
             "medium": "email", "campaign": "holiday", "is_unassigned": False},
        ],
        "dim_device": [
            {"device_key": 1, "device_category": "desktop"},
            {"device_key": 2, "device_category": "mobile"},
        ],
        "dim_user": [
            {"user_key": 1, "is_new_user": True},
            {"user_key": 2, "is_new_user": False},
            {"user_key": 3, "is_new_user": False},
        ],
        "fct_sessions": [
            *[_session(f"organic-{index}", 1 if index < 3 else 2, 20201218, 1, 1)
              for index in range(7)],
            _session("direct-1", 3, 20201218, 2, 2),
            _session("direct-2", 3, 20201218, 2, 2),
        ],
        "fct_daily_ecommerce": [
            # Two rows share one output grain: numerator and denominator must be summed.
            _mart(20201218, 1, 1, sessions=4, engaged_sessions=3, page_views=6,
                  engagement_time_msec=1000, view_item_events=4,
                  sessions_with_view_item=2, sessions_with_add_to_cart=1,
                  sessions_with_begin_checkout=1, sessions_with_add_shipping_info=1,
                  sessions_with_add_payment_info=1, sessions_with_purchase=1,
                  sessions_cart_and_purchase=1, sessions_checkout_and_purchase=1,
                  sessions_payment_and_purchase=1, orders=1, revenue_usd=120.0),
            _mart(20201218, 1, 1, sessions=3, engaged_sessions=1, page_views=4,
                  engagement_time_msec=2000, view_item_events=2,
                  sessions_with_view_item=2, sessions_with_add_to_cart=2,
                  sessions_with_begin_checkout=1, sessions_with_add_shipping_info=1,
                  sessions_with_purchase=2, sessions_cart_and_purchase=1,
                  orders=2, revenue_usd=180.0),
            # A purchase need not imply every preceding funnel flag is present.
            _mart(20201218, 2, 2, sessions=2, engaged_sessions=1,
                  engagement_time_msec=4000, sessions_with_purchase=1,
                  orders=2, revenue_usd=100.0),
            # Exercise LEFT JOIN user counts and null ratios with a separate Mart row.
            _mart(20201219, 3, 1, sessions=1),
        ],
    }
    for table, rows in tables.items():
        _insert_rows(connection, table, rows)
    yield connection
    connection.close()


def _create_real_view(connection, view_name):
    sql = (ROOT / "src" / "kpi" / f"{view_name}.sql").read_text(encoding="utf-8")
    pattern = (
        r'^CREATE\s+OR\s+REPLACE\s+VIEW\s+'
        r'`\$\{PROJECT_ID\}\.kpi\.([a-z_]+)`\s+AS'
    )
    sql, replacements = re.subn(
        pattern, lambda match: f"CREATE VIEW {match.group(1)} AS",
        sql, count=1, flags=re.IGNORECASE | re.MULTILINE,
    )
    assert replacements == 1
    sql = (sql.replace("${PROJECT_ID}.marts.", "")
              .replace("${PROJECT_ID}.core.", "").replace("`", ""))
    try:
        connection.executescript(sql)
    except sqlite3.Error:
        print(sql)
        raise


def _row_by_channel(connection, view_name):
    rows = connection.execute(
        f"SELECT * FROM {view_name} ORDER BY channel_group"
    ).fetchall()
    return {row["channel_group"]: dict(row) for row in rows}


def _assert_metrics(row, expected):
    for name, value in expected.items():
        assert name in row
        if value is None:
            assert row[name] is None
        elif isinstance(value, float):
            assert row[name] == pytest.approx(value)
        else:
            assert row[name] == value


def test_traffic_view_matches_hand_calculated_rows(database):
    _create_real_view(database, "v_kpi_traffic_engagement")
    rows = _row_by_channel(database, "v_kpi_traffic_engagement")
    assert set(rows) == {"Organic Search", "Direct", "Email"}
    _assert_metrics(rows["Organic Search"], {
        "event_date": "2020-12-18", "year_month": "202012", "is_weekend": False,
        "source": "google", "medium": "organic", "campaign": "launch",
        "device_category": "desktop", "sessions": 7, "engaged_sessions": 4,
        "page_views": 10, "engagement_time_msec": 3000,
        "users": 2, "new_users": 1, "sessions_per_user": 3.5,
        "engagement_rate": 4 / 7, "new_user_rate": 0.5,
    })
    _assert_metrics(rows["Direct"], {
        "sessions": 2, "users": 1, "new_users": 0,
        "sessions_per_user": 2.0, "engagement_rate": 0.5,
        "new_user_rate": 0.0,
    })
    _assert_metrics(rows["Email"], {
        "event_date": "2020-12-19", "users": 0, "new_users": 0,
        "sessions_per_user": None, "engagement_rate": 0.0,
        "new_user_rate": None,
    })


def test_funnel_view_uses_session_counts_and_intersections(database):
    _create_real_view(database, "v_kpi_funnel")
    rows = _row_by_channel(database, "v_kpi_funnel")
    _assert_metrics(rows["Organic Search"], {
        "event_date": "2020-12-18", "is_add_to_cart_tracked": True,
        "view_item_events": 6, "total_sessions": 7,
        "sessions_with_view_item": 4, "sessions_with_add_to_cart": 3,
        "sessions_with_begin_checkout": 2, "sessions_with_add_shipping_info": 2,
        "sessions_with_add_payment_info": 1, "sessions_with_purchase": 3,
        "sessions_cart_and_purchase": 2, "sessions_checkout_and_purchase": 1,
        "sessions_payment_and_purchase": 1,
        "add_to_cart_rate": 3 / 4, "begin_checkout_rate": 2 / 3,
        "shipping_info_rate": 1.0, "payment_info_rate": 0.5,
        "purchase_completion_rate": 1.0, "cart_abandonment_rate": 1 - 2 / 3,
    })
    _assert_metrics(rows["Direct"], {
        "total_sessions": 2, "sessions_with_purchase": 1,
        "add_to_cart_rate": None, "begin_checkout_rate": None,
        "shipping_info_rate": None, "payment_info_rate": None,
        "purchase_completion_rate": None, "cart_abandonment_rate": None,
    })
    assert rows["Email"]["is_add_to_cart_tracked"] == 0


def test_revenue_view_scopes_ratios_and_revenue_share(database):
    _create_real_view(database, "v_kpi_conversion_revenue")
    rows = _row_by_channel(database, "v_kpi_conversion_revenue")
    _assert_metrics(rows["Organic Search"], {
        "sessions": 7, "purchasing_sessions": 3, "orders": 3,
        "revenue_usd": 300.0, "users": 2,
        "conversion_rate": 3 / 7, "aov_usd": 100.0,
        "revenue_per_session_usd": 300 / 7, "revenue_per_user_usd": 150.0,
        "revenue_share_total": 0.75,
    })
    _assert_metrics(rows["Direct"], {
        "sessions": 2, "purchasing_sessions": 1, "orders": 2,
        "revenue_usd": 100.0, "users": 1,
        "conversion_rate": 0.5, "aov_usd": 50.0,
        "revenue_per_session_usd": 50.0, "revenue_per_user_usd": 100.0,
        "revenue_share_total": 0.25,
    })
    _assert_metrics(rows["Email"], {
        "revenue_usd": 0.0, "users": 0, "orders": 0,
        "conversion_rate": 0.0, "aov_usd": None,
        "revenue_per_session_usd": 0.0, "revenue_per_user_usd": None,
        "revenue_share_total": 0.0,
    })
