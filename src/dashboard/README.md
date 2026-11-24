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
| `analysis/` | Pure-pandas logic per feature (`compare.py`, `channel_quality.py`, `funnel.py`, `drilldown.py`), unit tested |
| `views/overview.py` | Feature 1: executive overview |
| `views/compare.py` | Feature 3: groups side by side with ranking; two periods |
| `views/channel_quality.py` | Feature 4: volume vs quality quadrants |
| `views/funnel.py` | Feature 5: 6-step funnel, segments heatmap, product groups |
| `views/drilldown.py` | Feature 6: channel → source/medium → campaign, month → week → day, product group → product |
| `views/planned.py` | Placeholders for features 7–10 (scope + data source) |

## Rules

- Pages never query BigQuery directly; they use `ctx.filtered` / `ctx.filtered_products`.
- Ratios are recomputed from numerators/denominators after filtering (`kpi.summarize`);
  never sum or average ratio columns.
- KPI names, units and formulas shown to users come from `kpi_dictionary.yaml`.
- To build a feature: put the logic in `analysis/<feature>.py` (no Streamlit), the page in
  `views/<feature>.py` with `render(ctx)`, register it in `app.py`, remove its entry from
  `views/planned.PLANNED`, add tests in `tests/test_dashboard_analysis.py`.

## Known data limits

- The product frame has no country or user-type dimension, so those two filters
  do not apply to product figures.
- New/returning (`is_new_user_session`) relies on the `first_visit` event; users
  first seen before 2020-11-01 only appear as returning.
- 01–10/11/2020 have no valid order: every purchase there has transaction_id `(not set)`
  (883 such purchases over the 92 days, USD 31,817 excluded). `kpi.no_valid_order_note`
  returns the caption pages show when a range touches those days.
- In the obfuscated data the items viewed/added to cart and the items purchased are almost
  disjoint catalogues (4 of 427 viewed item_ids were sold), so the funnel has no
  per-product view → purchase rate.
