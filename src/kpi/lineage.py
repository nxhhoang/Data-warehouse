# src/kpi/lineage.py
import os
import yaml
import pandas as pd
from pathlib import Path
from google.cloud import bigquery

class MetricLineageService:
    """Trace a KPI back to its definition, lineage path and source records.

    Powers the "number drill-down" feature of the dashboard (report section
    3.5, feature 10): given a KPI id and a filter, it returns the KPI
    definition from kpi_dictionary.yaml, the tables involved at each layer,
    and a sample of the Core-layer records that feed the number.

    Parameters
    ----------
    bq_client : bigquery.Client
        Client used to query the Core layer.
    project_id : str
        GCP project that owns the warehouse datasets.
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        self.client = bq_client
        self.project_id = project_id
        dict_path = Path(__file__).parent / "kpi_dictionary.yaml"
        with open(dict_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.kpi_map = {item["id"]: item for item in data["kpis"]}

    def trace_metric(self, kpi_id: str, start_date: str, end_date: str,
                     channel: str | None = None, device: str | None = None) -> dict:
        """Build the full lineage of one KPI for a given filter.

        Parameters
        ----------
        kpi_id : str
            KPI identifier as defined in kpi_dictionary.yaml.
        start_date : str
            First day of the range, formatted as YYYY-MM-DD.
        end_date : str
            Last day of the range, formatted as YYYY-MM-DD.
        channel : str, optional
            Channel group filter; None or "All" disables the filter.
        device : str, optional
            Device category filter; None or "All" disables the filter.

        Returns
        -------
        dict
            Keys 'definition' (formula and caveats), 'lineage_path'
            (raw source -> staging -> core -> mart -> KPI), 'executed_sample_sql',
            'sample_records' (pandas DataFrame of up to 50 Core-layer rows)
            and 'quality_notes'.
        """
        meta = self.kpi_map[kpi_id]
        where_clauses = [f"d.full_date BETWEEN '{start_date}' AND '{end_date}'"]
        if channel and channel != "All":
            where_clauses.append(f"ts.channel_group = '{channel}'")
        if device and device != "All":
            where_clauses.append(f"dev.device_category = '{device}'")
        where_sql = " AND ".join(where_clauses)

        # Sample the source records from the Core layer
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

    def _read_quality_summary(self, start_date: str, end_date: str) -> list[dict]:
        """Aggregate the quality log written by the pipeline for a date range.

        Reads the quality_log table in the raw dataset (RAW_DATASET env var,
        default marketing_dss_raw) written by the Dataflow pipeline, matching
        the fields of config/quality_rules.yaml. Returns an empty list when
        the table does not exist yet (e.g. before the first pipeline run).

        Parameters
        ----------
        start_date : str
            First day of the range, formatted as YYYY-MM-DD.
        end_date : str
            Last day of the range, formatted as YYYY-MM-DD.

        Returns
        -------
        list of dict
            One entry per (rule_name, action) with its total affected_rows.
        """
        raw_dataset = os.environ.get("RAW_DATASET", "marketing_dss_raw")
        query = f"""
            SELECT rule_name, action, SUM(affected_rows) AS affected_rows
            FROM `{self.project_id}.{raw_dataset}.quality_log`
            WHERE run_date BETWEEN @start_date AND @end_date
            GROUP BY rule_name, action
            ORDER BY affected_rows DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
                bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
            ]
        )
        try:
            rows = self.client.query(query, job_config=job_config).result()
            return [dict(row) for row in rows]
        except Exception:
            return []