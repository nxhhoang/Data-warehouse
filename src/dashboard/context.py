"""State handed by app.py to every page."""

from dataclasses import dataclass, field

import pandas as pd

from src.dashboard.config import Settings
from src.dashboard.filters import Filters, apply_filters, apply_product_filters


@dataclass
class PageContext:
    """Loaded data plus the current filter state.

    Attributes
    ----------
    settings : Settings
        Runtime settings (data source, project, alert threshold).
    sessions : pandas.DataFrame
        All sessions (unfiltered), schema data.SESSION_COLUMNS.
    products : pandas.DataFrame
        Date × product × channel × device frame, schema data.PRODUCT_COLUMNS.
    filters : Filters
        Filters chosen in the sidebar.
    pages : dict
        url_path -> st.Page, filled by app.py, for links between pages.
    """

    settings: Settings
    sessions: pd.DataFrame
    products: pd.DataFrame
    filters: Filters
    pages: dict = field(default_factory=dict)

    @property
    def filtered(self) -> pd.DataFrame:
        """Sessions matching the sidebar filters."""
        return apply_filters(self.sessions, self.filters)

    @property
    def filtered_products(self) -> pd.DataFrame:
        """Product rows matching the date, channel and device filters."""
        return apply_product_filters(self.products, self.filters)
