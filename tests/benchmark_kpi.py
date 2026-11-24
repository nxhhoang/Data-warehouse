"""Query latency benchmark (milestone M5 acceptance, report section 4).

Runs a fixed set of dashboard-style queries against the Raw layer
(events_* tables) and against the Marts/KPI views, then reports latency,
bytes scanned, and whether each Marts/KPI query meets the 3-second target.
Results are saved to tests/benchmark_results.json.
"""

import os
import time
import json
from pathlib import Path
from google.cloud import bigquery

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path = REPO_ROOT / ".env") -> None:
    """Load key/value pairs from a .env file if it exists; never overwrite."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def run_benchmark(project_id: str) -> list[dict]:
    """Run all benchmark queries and collect timing results.

    Parameters
    ----------
    project_id : str
        GCP project that owns the kpi, marts and core datasets.

    Returns
    -------
    list of dict
        One entry per query with keys 'query_name', 'layer',
        'latency_sec', 'bytes_processed', 'mb_processed' and 'status'
        (PASS / FAIL for Marts/KPI queries under 3 s, BASELINE for raw).
    """
    client = bigquery.Client(project=project_id)

    queries = [
        {
            "name": "Q1_Overview_Daily_KPI_Raw",
            "layer": "Raw (events_*)",
            # Same valid-order filters as stg_valid_orders.sql / assert_kpi_vs_raw_parity.sql:
            # placeholder transaction_id excluded, revenue > 0, dedup keep earliest event.
            "sql": """
                WITH valid_orders AS (
                    SELECT
                        user_pseudo_id,
                        ecommerce.transaction_id AS transaction_id,
                        ecommerce.purchase_revenue_in_usd AS revenue_usd
                    FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
                    WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
                      AND event_name = 'purchase'
                      AND ecommerce.transaction_id IS NOT NULL
                      AND TRIM(ecommerce.transaction_id) NOT IN ('(not set)', '<Other>', '(data deleted)', '')
                      AND ecommerce.purchase_revenue_in_usd > 0
                    QUALIFY ROW_NUMBER() OVER (
                        PARTITION BY user_pseudo_id, ecommerce.transaction_id
                        ORDER BY event_timestamp ASC, event_bundle_sequence_id ASC
                    ) = 1
                )
                SELECT
                    e.event_date,
                    COUNT(DISTINCT CONCAT(e.user_pseudo_id, '_',
                        CAST((SELECT value.int_value FROM UNNEST(e.event_params) WHERE key = 'ga_session_id' LIMIT 1) AS STRING)
                    )) AS sessions,
                    (SELECT SUM(revenue_usd) FROM valid_orders) AS revenue
                FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` e
                WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
                GROUP BY e.event_date
            """,
        },
        {
            "name": "Q1_Overview_Daily_KPI_Mart",
            "layer": "Marts / KPI View",
            "sql": f"""
                SELECT
                    event_date,
                    SUM(sessions) AS sessions,
                    SUM(revenue_usd) AS revenue
                FROM `{project_id}.kpi.v_kpi_conversion_revenue`
                GROUP BY event_date
            """,
        },
        {
            "name": "Q2_Channel_Comparison_Mart",
            "layer": "Marts / KPI View",
            "sql": f"""
                SELECT
                    channel_group,
                    SUM(sessions) AS sessions,
                    SAFE_DIVIDE(SUM(purchasing_sessions), SUM(sessions)) AS conversion_rate,
                    SUM(revenue_usd) AS revenue_usd,
                    SAFE_DIVIDE(SUM(revenue_usd), SUM(orders)) AS aov_usd
                FROM `{project_id}.kpi.v_kpi_conversion_revenue`
                GROUP BY channel_group
                ORDER BY revenue_usd DESC
            """,
        },
        {
            "name": "Q3_Funnel_By_Device_Mart",
            "layer": "Marts / KPI View",
            "sql": f"""
                SELECT
                    device_category,
                    SUM(sessions_with_view_item) AS view_item_sessions,
                    SUM(sessions_with_add_to_cart) AS cart_sessions,
                    SUM(sessions_with_begin_checkout) AS checkout_sessions,
                    SUM(sessions_with_purchase) AS purchase_sessions
                FROM `{project_id}.kpi.v_kpi_funnel`
                WHERE is_add_to_cart_tracked = TRUE
                GROUP BY device_category
            """,
        },
        {
            "name": "Q4_Top_Products_Drilldown_Mart",
            "layer": "Marts / Core",
            "sql": f"""
                SELECT
                    p.item_category,
                    p.item_name,
                    SUM(f.item_view_events) AS views,
                    SUM(f.units_sold) AS units_sold,
                    SUM(f.item_revenue_usd) AS revenue_usd
                FROM `{project_id}.marts.fct_product_performance` f
                JOIN `{project_id}.core.dim_product` p ON f.product_key = p.product_key
                GROUP BY 1, 2
                ORDER BY revenue_usd DESC
                LIMIT 20
            """,
        },
    ]

    results = []
    job_config = bigquery.QueryJobConfig(use_query_cache=False)

    print(f"{'Query':<34} | {'Layer':<18} | {'Latency (s)':<12} | {'Bytes Scanned':<15} | {'M5 (<3s)'}")
    print("-" * 96)

    for q in queries:
        t0 = time.perf_counter()
        job = client.query(q["sql"], job_config=job_config)
        _ = list(job.result())
        elapsed = round(time.perf_counter() - t0, 3)
        bytes_proc = job.total_bytes_processed or 0
        passed = "PASS" if (q["layer"] != "Raw (events_*)" and elapsed < 3.0) else ("BASELINE" if q["layer"] == "Raw (events_*)" else "FAIL")

        row = {
            "query_name": q["name"],
            "layer": q["layer"],
            "latency_sec": elapsed,
            "bytes_processed": bytes_proc,
            "mb_processed": round(bytes_proc / (1024 * 1024), 2),
            "status": passed,
        }
        results.append(row)
        print(f"{row['query_name']:<34} | {row['layer']:<18} | {row['latency_sec']:<12} | {row['mb_processed']:>10.2f} MB | {row['status']}")

    return results


if __name__ == "__main__":
    load_env_file()
    PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "your-gcp-project-id")
    out = run_benchmark(PROJECT_ID)
    out_path = Path(__file__).resolve().parent / "benchmark_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved benchmark report to {out_path}")