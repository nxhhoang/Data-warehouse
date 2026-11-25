"""Deterministic mock data with the same columns as the BigQuery source.

Lets the dashboard and its tests run without a GCP account while the
warehouse is not deployed. The numbers are synthetic, but their shape follows
the data survey: 92 days, a year-end peak, add_to_cart missing on 18 days,
a 6-step funnel where purchases can happen without an add_to_cart.
"""

import numpy as np
import pandas as pd

from src.dashboard.config import CHANNEL_GROUPS, DATA_END, DATA_START

SEED = 4031

# channel -> (traffic share, purchase multiplier, source, medium)
_CHANNELS = {
    "Direct": (0.30, 1.0, "(direct)", "(none)"),
    "Organic Search": (0.28, 1.1, "google", "organic"),
    "Paid Search": (0.06, 1.4, "google", "cpc"),
    "Display": (0.03, 0.4, "google", "display"),
    "Email": (0.01, 1.8, "newsletter", "email"),
    "Affiliate": (0.01, 0.8, "partner", "affiliate"),
    "Paid Social": (0.01, 0.6, "facebook", "paid-social"),
    "Organic Social": (0.02, 0.5, "youtube.com", "social"),
    "Referral": (0.10, 1.3, "shop.googlemerchandisestore.com", "referral"),
    "Unknown": (0.18, 0.9, "Unknown", "Unknown"),
}
assert tuple(_CHANNELS) == CHANNEL_GROUPS

_DEVICES = {"desktop": 0.57, "mobile": 0.40, "tablet": 0.02, "Unknown": 0.01}
_OS = {"desktop": ["Windows", "Macintosh", "Linux"], "mobile": ["iOS", "Android"],
       "tablet": ["iOS", "Android"], "Unknown": ["Unknown"]}
_COUNTRIES = {
    "United States": ("Americas", 0.44), "India": ("Asia", 0.09),
    "Canada": ("Americas", 0.07), "United Kingdom": ("Europe", 0.04),
    "France": ("Europe", 0.03), "Spain": ("Europe", 0.03),
    "Taiwan": ("Asia", 0.02), "Japan": ("Asia", 0.02),
    "Vietnam": ("Asia", 0.01), "Unknown": ("Unknown", 0.25),
}
_LANDING = {"home": 0.45, "product": 0.30, "other": 0.15, "cart": 0.05,
            "checkout": 0.02, "Unknown": 0.03}
_CAMPAIGNS = ["(organic)", "(referral)", "Data Share Promo", "<Other>", "Unknown"]
_CATEGORIES = ["Apparel", "Drinkware", "Bags", "Office", "Lifestyle",
               "Accessories", "Campus Collection", "Unknown"]

# Funnel conditional probabilities (step k given step k-1)
_P_VIEW = 0.30
_P_CART, _P_CHECKOUT, _P_SHIP, _P_PAY, _P_BUY = 0.28, 0.45, 0.72, 0.78, 0.55


def _dates() -> pd.DatetimeIndex:
    return pd.date_range(DATA_START, DATA_END, freq="D")


def _day_weights(dates: pd.DatetimeIndex) -> np.ndarray:
    """Relative daily traffic: weekday dip on weekends, year-end peak."""
    w = np.where(dates.day_of_week >= 5, 0.75, 1.0)
    peak = (dates >= "2020-11-25") & (dates <= "2020-12-15")
    w = np.where(peak, w * 1.6, w)
    w = np.where(dates >= "2020-12-24", w * 0.7, w)
    return w / w.sum()


def untracked_add_to_cart_days() -> pd.DatetimeIndex:
    """The 18 days on which the mock, like the real data, has no add_to_cart."""
    rng = np.random.default_rng(SEED + 1)
    days = _dates()
    return pd.DatetimeIndex(sorted(rng.choice(days, size=18, replace=False)))


def make_sessions(n_sessions: int = 80_000, seed: int = SEED) -> pd.DataFrame:
    """Generate a session-level frame matching data.SESSION_COLUMNS.

    Parameters
    ----------
    n_sessions : int, optional
        Number of sessions to generate. Default 80,000 (kept below the real
        ~360k so the app starts fast).
    seed : int, optional
        Random seed; the same seed always yields the same frame.
    """
    rng = np.random.default_rng(seed)
    n = n_sessions
    dates = _dates()

    session_date = rng.choice(dates, size=n, p=_day_weights(dates))
    channel = rng.choice(list(_CHANNELS), size=n, p=[v[0] for v in _CHANNELS.values()])
    device = rng.choice(list(_DEVICES), size=n, p=list(_DEVICES.values()))
    country = rng.choice(list(_COUNTRIES), size=n, p=[v[1] for v in _COUNTRIES.values()])

    # ~1.3 sessions per user; a user keeps one first-visit flag
    n_users = int(n / 1.3)
    user_key = rng.integers(1, n_users + 1, size=n)
    new_user_by_key = rng.random(n_users + 1) < 0.8

    buy_mult = pd.Series(channel).map({k: v[1] for k, v in _CHANNELS.items()}).to_numpy()
    mobile_penalty = np.where(device == "mobile", 0.7, 1.0)

    has_view = rng.random(n) < _P_VIEW
    cart = has_view & (rng.random(n) < _P_CART)
    checkout = cart & (rng.random(n) < _P_CHECKOUT)
    ship = checkout & (rng.random(n) < _P_SHIP)
    pay = ship & (rng.random(n) < _P_PAY)
    buy = pay & (rng.random(n) < np.clip(_P_BUY * buy_mult * mobile_penalty, 0, 0.95))

    untracked = pd.DatetimeIndex(session_date).isin(untracked_add_to_cart_days())
    has_cart = cart & ~untracked

    order_count = np.where(buy, 1 + (rng.random(n) < 0.03), 0)
    revenue = np.where(buy, np.round(rng.lognormal(4.3, 0.8, size=n) * order_count, 2), 0.0)
    engaged = rng.random(n) < np.where(has_view, 0.9, 0.55)
    page_views = 1 + rng.poisson(np.where(engaged, 3.5, 0.6))
    view_items = np.where(has_view, 1 + rng.poisson(1.5, size=n), 0)

    source = pd.Series(channel).map({k: v[2] for k, v in _CHANNELS.items()})
    medium = pd.Series(channel).map({k: v[3] for k, v in _CHANNELS.items()})
    ts_dates = pd.DatetimeIndex(session_date)

    # Order each user's sessions in time: the first one holds first_visit when
    # the user is new; returning users already had 1-5 sessions before Nov 1
    order = pd.DataFrame({"user_key": user_key, "date": session_date}).sort_values(
        ["user_key", "date"], kind="stable")
    nth = np.empty(n, dtype=int)
    nth[order.index.to_numpy()] = order.groupby("user_key").cumcount().to_numpy() + 1
    is_new = new_user_by_key[user_key]
    prior_sessions = np.where(is_new, 0, rng.integers(1, 6, size=n_users + 1)[user_key])

    # Order each user's sessions in time: the first one holds first_visit when
    # the user is new; returning users already had 1-5 sessions before Nov 1
    order = pd.DataFrame({"user_key": user_key, "date": session_date}).sort_values(
        ["user_key", "date"], kind="stable")
    nth = np.empty(n, dtype=int)
    nth[order.index.to_numpy()] = order.groupby("user_key").cumcount().to_numpy() + 1
    is_new = new_user_by_key[user_key]
    prior_sessions = np.where(is_new, 0, rng.integers(1, 6, size=n_users + 1)[user_key])

    return pd.DataFrame({
        "session_id": [f"mock-{i:07d}" for i in range(n)],
        "user_key": user_key,
        "session_date": ts_dates,
        "is_weekend": ts_dates.day_of_week >= 5,
        "is_holiday_season": (ts_dates >= "2020-11-25") & (ts_dates <= "2020-12-31"),
        "is_add_to_cart_tracked": ~untracked,
        "channel_group": channel,
        "source": source,
        "medium": medium,
        "campaign": rng.choice(_CAMPAIGNS, size=n),
        "attribution_basis": np.where(rng.random(n) < 0.85, "session", "user_fallback"),
        "device_category": device,
        "operating_system": np.select(
            [device == "desktop", np.isin(device, ["mobile", "tablet"])],
            [rng.choice(_OS["desktop"], size=n), rng.choice(_OS["mobile"], size=n)],
            default="Unknown",
        ),
        "continent": pd.Series(country).map({k: v[0] for k, v in _COUNTRIES.items()}),
        "country": country,
        "landing_page_type": rng.choice(list(_LANDING), size=n, p=list(_LANDING.values())),
        "is_new_user": is_new,
        "is_new_user_session": (is_new & (nth == 1)).astype(int),
        "user_session_number": nth + prior_sessions,
        "event_count": page_views + view_items + 2 + 3 * buy,
        "page_view_count": page_views,
        "view_item_count": view_items,
        "engagement_time_msec": np.where(engaged, rng.integers(10_000, 600_000, size=n), 0),
        "is_engaged": engaged.astype(int),
        "has_view_item": has_view.astype(int),
        "has_add_to_cart": has_cart.astype(int),
        "has_begin_checkout": checkout.astype(int),
        "has_add_shipping_info": ship.astype(int),
        "has_add_payment_info": pay.astype(int),
        "has_purchase": buy.astype(int),
        "order_count": order_count,
        "revenue_usd": revenue,
    })


def make_products(n_products: int = 150, seed: int = SEED) -> pd.DataFrame:
    """Generate a date × product × channel × device frame matching data.PRODUCT_COLUMNS."""
    rng = np.random.default_rng(seed + 2)
    items = pd.DataFrame({
        "item_id": [f"GGOE{i:05d}" for i in range(n_products)],
        "item_category": rng.choice(_CATEGORIES, size=n_products),
        "item_brand": rng.choice(["Google", "YouTube", "Android", "Unknown"], size=n_products),
        "price": np.round(rng.lognormal(2.8, 0.6, size=n_products), 2),
        "popularity": rng.lognormal(0, 1, size=n_products),
    })
    items["item_name"] = items["item_brand"] + " " + items["item_category"] + " #" + items.index.astype(str)
    channels = pd.DataFrame({
        "channel_group": list(_CHANNELS),
        "channel_share": [v[0] for v in _CHANNELS.values()],
        "buy_mult": [v[1] for v in _CHANNELS.values()],
    })
    devices = pd.DataFrame({"device_category": list(_DEVICES),
                            "device_share": list(_DEVICES.values())})

    grid = (items.merge(pd.DataFrame({"date": _dates()}), how="cross")
            .merge(channels, how="cross").merge(devices, how="cross"))
    lam = grid["popularity"] * 6 * grid["channel_share"] * grid["device_share"]
    views = rng.poisson(lam.to_numpy())
    carts = rng.binomial(views, 0.12)
    checkouts = rng.binomial(carts, 0.5)
    sold = rng.binomial(checkouts, np.clip(0.6 * grid["buy_mult"].to_numpy(), 0, 0.95))
    untracked = grid["date"].isin(untracked_add_to_cart_days()).to_numpy()
    grid["item_view_events"] = views
    grid["item_add_to_cart_events"] = np.where(untracked, 0, carts)
    grid["item_checkout_events"] = checkouts
    grid["units_sold"] = sold
    grid["item_revenue_usd"] = np.round(sold * grid["price"], 2)
    # The real mart only has rows with at least one event or sale
    active = (views + checkouts + sold) > 0
    return (grid.loc[active]
            .drop(columns=["price", "popularity", "channel_share", "buy_mult", "device_share"])
            .reset_index(drop=True))
