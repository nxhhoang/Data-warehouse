"""Number formatting (Vietnamese style: 1.234,5) and chart styling."""

import math

# Categorical slots, fixed order (dataviz reference palette, light mode).
# Colour follows the entity, never its rank: a channel keeps its colour
# whatever the filter. 'Unknown' is neutral grey; channels without a slot
# are folded into "Khác" by pages that colour by channel.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#6250d6", "#e34948"]
NEUTRAL = "#8a8986"
CHANNEL_COLORS = {
    "Direct": SERIES[0],
    "Organic Search": SERIES[1],
    "Referral": SERIES[2],
    "Paid Search": SERIES[3],
    "Display": SERIES[4],
    "Email": SERIES[5],
    "Organic Social": SERIES[6],
    "Paid Social": SERIES[7],
    "Unknown": NEUTRAL,
}
PRIMARY = SERIES[0]


def _vn(number: float, decimals: int) -> str:
    """Format with '.' thousands and ',' decimal separators."""
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def fmt_value(value: float, unit: str) -> str:
    """Format a KPI value according to its dictionary ``unit``."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if unit == "%":
        return _vn(value * 100, 2) + "%"
    if unit.startswith("USD"):
        return "$" + _vn(value, 2)
    if float(value).is_integer():
        return _vn(value, 0)
    return _vn(value, 2)


def fmt_delta(change: float) -> str | None:
    """Relative change for st.metric, or None when there is no comparison."""
    # No arrow for "no change": a +0,0% in green reads as growth
    if change is None or math.isnan(change) or abs(change) < 0.0005:
        return None
    return ("+" if change >= 0 else "") + _vn(change * 100, 1) + "%"


def fmt_signed_usd(value: float) -> str:
    """Signed USD amount; float noise under half a cent prints as $0,00 without a sign."""
    if abs(value) < 0.005:
        return fmt_value(0.0, "USD")
    return ("+" if value > 0 else "−") + fmt_value(abs(value), "USD")


def kpi_display_table(table, key_col: str, key_label: str, kpi_ids, extra=None):
    """Copy of ``table`` with KPI columns formatted and renamed for st.dataframe.

    Parameters
    ----------
    table : pandas.DataFrame
        Must contain ``key_col`` and every id of ``kpi_ids``.
    key_col, key_label : str
        Grouping column and its display name.
    kpi_ids : iterable of str
        KPI ids (dictionary) to show, in order.
    extra : dict, optional
        Other column -> display name, appended unformatted.
    """
    from src.dashboard import kpi

    extra = extra or {}
    shown = table[[key_col, *kpi_ids, *extra]].copy()
    for kpi_id in kpi_ids:
        shown[kpi_id] = shown[kpi_id].map(lambda v, u=kpi.unit(kpi_id): fmt_value(v, u))
    return shown.rename(columns={key_col: key_label, **{k: kpi.label(k) for k in kpi_ids}, **extra})


def style_figure(fig, height: int = 360):
    """Recessive axes/grid, thin marks, unified hover; returns ``fig``."""
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        hovermode="x unified",
        showlegend=False,
        separators=",.",
    )
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", zeroline=False, title=None)
    return fig
