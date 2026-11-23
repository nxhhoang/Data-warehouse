# src/kpi/lineage.py
import yaml
import pandas as pd
from pathlib import Path
from google.cloud import bigquery

class MetricLineageService:
    def __init__(self, bq_client: bigquery.Client, project_id: str):
        self.client = bq_client
        self.project_id = project_id
        dict_path = Path(__file__).parent / "kpi_dictionary.yaml"
        with open(dict_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.kpi_map = {item["id"]: item for item in data["kpis"]}

    def trace_metric(self, kpi_id: str, start_date: str, end_date: str,
                     channel: str | None = None, device: str | None = None) -> dict:
        meta = self.kpi_map[kpi_id]
        where_clauses = [f"d.full_date BETWEEN '{start_date}' AND '{end_date}'"]
        if channel and channel != "All":
            where_clauses.append(f"ts.channel_group = '{channel}'")
        if device and device != "All":
            where_clauses.append(f"dev.device_category = '{device}'")
        where_sql = " AND ".join(where_clauses)

        # Truy vấn mẫu bản ghi nguồn từ tầng Core
        sample_sql = f"""
        SELECT
            s.session_id,
            d.full_date AS session_date,
            ts.channel_group,
            s.attribution_basis,
            dev.device_category,
            s.has_view_item,
            s.has_add_to_cart,
            s.has_begin_checkout,
            s.has_purchase,
            s.order_count,
            s.revenue_usd
        FROM `{self.project_id}.core.fct_sessions` s
        JOIN `{self.project_id}.core.dim_date` d ON s.date_key = d.date_key
        JOIN `{self.project_id}.core.dim_traffic_source` ts ON s.session_source_key = ts.traffic_source_key
        JOIN `{self.project_id}.core.dim_device` dev ON s.device_key = dev.device_key
        WHERE {where_sql}
        ORDER BY s.revenue_usd DESC, s.session_id
        LIMIT 50
        """
        sample_df = self.client.query(sample_sql).to_dataframe()

        return {
            "definition": {
                "name": meta["name"],
                "group": meta["group"],
                "formula_text": meta["formula_text"],
                "sql_formula": meta["sql_formula"],
                "caveats": meta.get("caveats", []),
            },
            "lineage_path": [
                meta["raw_source"],
                "staging.stg_ga4_events / stg_valid_orders",
                " -> ".join(meta["core_tables"]),
                meta["mart_table"],
                f"kpi.{kpi_id}",
            ],
            "executed_sample_sql": sample_sql.strip(),
            "sample_records": sample_df,
            "quality_notes": self._read_quality_summary(start_date, end_date),
        }