"""Feature 4 — channel quality: traffic volume versus traffic quality.

Each group (channel, or source / medium) lands in one quadrant:
volume is "large" at or above the median sessions of the eligible groups,
quality is "good" at or above the overall value of the filtered slice.
"""

import numpy as np
import pandas as pd

from src.dashboard import kpi

QUALITY_KPIS = ("conversion_rate", "revenue_per_session_usd", "engagement_rate")

CORE = "Chủ lực"
LEAKY = "Nhiều truy cập, ít chuyển đổi"
NICHE = "Ít truy cập, chuyển đổi tốt"
WEAK = "Ít truy cập, chất lượng thấp"
SMALL = "Chưa đủ dữ liệu"

# What each quadrant suggests to the decision maker
ADVICE = {
    CORE: "Duy trì, bảo vệ ngân sách",
    LEAKY: "Xem lại trang đích và mức phù hợp của lưu lượng",
    NICHE: "Ứng viên mở rộng quy mô",
    WEAK: "Cân nhắc cắt giảm hoặc thử nghiệm lại",
    SMALL: "Theo dõi thêm trước khi kết luận",
}


def classify(df: pd.DataFrame, by: str, quality_kpi: str,
             min_sessions: int = 100) -> tuple[pd.DataFrame, float, float]:
    """KPIs per group of ``by`` plus its quadrant.

    Returns
    -------
    table : pandas.DataFrame
        kpi.breakdown(df, by) with ``session_share``, ``quadrant`` and ``advice``.
    volume_cut : float
        Median sessions of the groups with at least ``min_sessions``.
    quality_cut : float
        ``quality_kpi`` over the whole of ``df`` (the filtered average).
    """
    table = kpi.breakdown(df, by)
    quality_cut = kpi.summarize(df)[quality_kpi]
    if table.empty:
        return table, np.nan, quality_cut

    table["session_share"] = table["sessions"] / table["sessions"].sum()
    eligible = table["sessions"] >= min_sessions
    volume_cut = float(table.loc[eligible, "sessions"].median()) if eligible.any() else np.nan

    large = table["sessions"] >= volume_cut
    good = table[quality_kpi] >= quality_cut
    table["quadrant"] = np.select(
        [~eligible, large & good, large & ~good, ~large & good],
        [SMALL, CORE, LEAKY, NICHE], default=WEAK)
    table["advice"] = table["quadrant"].map(ADVICE)
    return table, volume_cut, quality_cut
