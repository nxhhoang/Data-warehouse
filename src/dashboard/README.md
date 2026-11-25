# Dashboard (layer 5)

Streamlit + Plotly app for the 10 decision-support features (report section 3.5).

## Run

All commands run from the repository root.

### First time only: set up the environment

```bash
python3.12 -m venv .venv          # needs Python 3.10+ (macOS system python3 is 3.9)
bash scripts/setup_venv.sh        # installs requirements.txt into .venv
cp .env.example .env              # then edit values if needed
```

`setup_venv.sh` only creates `.venv` when it is missing, so creating it first
with `python3.12` makes sure the right Python version is used.

### Every time: run the dashboard

```bash
.venv/bin/streamlit run src/dashboard/app.py
```

Or activate the environment once per terminal, then call commands directly:

```bash
source .venv/bin/activate
streamlit run src/dashboard/app.py
pytest tests/test_dashboard.py    # dashboard tests
```

Streamlit prints the URL (default http://localhost:8501). Stop it with `Ctrl+C`.
Code changes are picked up when you click **Rerun** in the app or press `R`;
restart the command if a changed module is not reloaded.

### Re-run `setup_venv.sh` only when

- `requirements.txt` changed (e.g. after `git pull` added a package), or
- `.venv` was deleted or is broken (an `import` error for a listed package).

`DASHBOARD_DATA_SOURCE` in `.env` picks the data:

| Value | Reads | Needs |
|---|---|---|
| `mock` (default) | Synthetic data from `mock.py` | Nothing |
| `bigquery` | `core.fct_sessions` + dims, `marts.fct_product_channel_daily` + dims | `GCP_PROJECT_ID`, `gcloud auth application-default login`, warehouse built by `scripts/rebuild_warehouse.sh` |

## Management views

The sidebar has four management tabs: **Tất cả**, **CMO**, **Manager**, and
**Specialist**. They filter only the navigation pages, not access control; the
shared filters remain available to every role.

- **CMO**: Tổng quan, So sánh, Chất lượng kênh, Cảnh báo,
  Mô phỏng, Truy vết.
- **Manager**: So sánh, Chất lượng kênh, Chi tiết, Cảnh báo,
  Mô phỏng, Truy vết.
- **Specialist**: Phễu, Chi tiết, Phân khúc, Truy vết.

Choosing a new role opens that role's first page. Choosing a role whose set
includes the current page keeps user context. Definitions are centralized in
`src/dashboard/roles.py`, with tests in `tests/test_dashboard_roles.py`.

## Layout

| File | Role |
|---|---|
| `app.py` | Entry point: loads data once (`st.cache_data`), draws the sidebar filters, page navigation |
| `config.py` | Settings from `.env`, channel/device value lists |
| `data.py` | **Only** module that reads data. Defines the session and product frame schemas and the BigQuery SQL |
| `mock.py` | Deterministic mock data with the same schema (92 days, 18 days without `add_to_cart`) |
| `kpi.py` | Pure-pandas KPI formulas, mirroring `src/kpi/kpi_dictionary.yaml` |
| `filters.py` | Feature 2: filter state, `apply_filters`, sidebar widgets |
| `formatting.py` | Vietnamese number format, chart palette and styling |
| `context.py` | `PageContext` handed to every page |
| `analysis/` | Pure-pandas logic per feature (`compare.py`, `channel_quality.py`, `funnel.py`, `drilldown.py`, `segments.py`, `alerts.py`, `scenario.py`, `trace.py`), unit tested |
| `views/overview.py` | Feature 1: executive overview |
| `views/compare.py` | Feature 3: groups side by side with ranking; two periods |
| `views/channel_quality.py` | Feature 4: volume vs quality quadrants |
| `views/funnel.py` | Feature 5: 6-step funnel, segments heatmap, product groups |
| `views/drilldown.py` | Feature 6: channel → source/medium → campaign, month → week → day, product group → product |
| `views/segments.py` | Feature 7: segment profiles against the average, two-dimension matrix |
| `views/alerts.py` | Feature 8: threshold alerts, latest window vs the one before |
| `views/scenario.py` | Feature 9: per-channel traffic / conversion what-if |
| `views/trace.py` | Feature 10: definition, numerator/denominator, lineage, source sessions, warehouse check |

## Rules

- Pages never query BigQuery directly; they use `ctx.filtered` / `ctx.filtered_products`.
- Ratios are recomputed from numerators/denominators after filtering (`kpi.summarize`);
  never sum or average ratio columns.
- KPI names, units and formulas shown to users come from `kpi_dictionary.yaml`.
- To change a feature: logic lives in `analysis/<feature>.py` (no Streamlit, unit tested in
  `tests/test_dashboard_analysis.py`), the page in `views/<feature>.py` with `render(ctx)`,
  registered in `app.py`. Links between pages go through `ctx.pages[url_path]`.

## Known data limits

- The product frame has no country or user-type dimension, so those two filters
  do not apply to product figures.
- New/returning (`is_new_user_session`) relies on the `first_visit` event; users
  first seen before 2020-11-01 only appear as returning.
- Two data gaps make orders and revenue fall for data reasons: 01–10/11/2020 (every
  purchase has transaction_id `(not set)`) and 26–31/01/2021 (232 of 282 purchases lack a
  transaction_id and the source revenue nearly stops). 883 purchases with `(not set)` (USD
  31,817) are excluded over the 92 days. `kpi.data_gap_note` returns the caption pages show
  when a range touches a gap.
- In the obfuscated data the items viewed/added to cart and the items purchased are almost
  disjoint catalogues (4 of 427 viewed item_ids were sold), so the funnel has no
  per-product view → purchase rate.
