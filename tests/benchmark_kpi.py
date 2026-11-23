import os
import time
import json
from pathlib import Path
from google.cloud import bigquery


def run_benchmark(project_id: str) -> list[dict]:
    client = bigquery.Client(project=project_id)

    queries = [
        {
            "name": "Q1_Overview_Daily_KPI_Raw",
            "layer": "Raw (events_*)",
            "sql": """
                SELECT
                    event_date,
                    COUNT(DISTINCT CONCAT(user_pseudo_id, '_',
                        CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id' LIMIT 1) AS STRING)
                    )) AS sessions,
                    SUM(CASE WHEN event_name = 'purchase' AND ecommerce.transaction_id IS NOT NULL
                        AND ecommerce.transaction_id != '(not set)' THEN ecommerce.purchase_revenue_in_usd ELSE 0 END) AS revenue
                FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
                WHERE _TABLE_SUFFIX BETWEEN '20201101' AND '20210131'
                GROUP BY event_date
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
    PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "your-gcp-project-id")
    out = run_benchmark(PROJECT_ID)
    out_path = Path(__file__).resolve().parent / "benchmark_results.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved benchmark report to {out_path}")