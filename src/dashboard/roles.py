"""Management-level navigation for the dashboard.

This is presentation-level filtering, not authentication or authorization.
Every user can still choose "Tất cả" and inspect every page. The role pages
mirror the decision needs in report section 2.4, with the core pages remaining
unchanged regardless of role.
"""

ROLE_OPTIONS = ("all", "cmo", "manager", "specialist")

ROLE_LABELS = {
    "all": "Tất cả",
    "cmo": "CMO",
    "manager": "Manager",
    "specialist": "Specialist",
}

# Actual page URL paths, in navigation order. Keep this registry the single
# source of truth for every role, including 'all'.
PAGE_URLS = (
    "tong-quan",
    "so-sanh",
    "chat-luong-kenh",
    "pheu",
    "chi-tiet",
    "phan-khuc",
    "canh-bao",
    "mo-phong",
    "truy-vet",
)

ROLE_PAGES = {
    # Executive overview, investment comparison and scenario planning.
    "cmo": frozenset({
        "tong-quan", "so-sanh", "chat-luong-kenh", "canh-bao", "mo-phong",
        "truy-vet",
    }),
    # Digital marketing comparison, channel diagnosis, alerting and simulation.
    "manager": frozenset({
        "so-sanh", "chat-luong-kenh", "chi-tiet", "canh-bao", "mo-phong",
        "truy-vet",
    }),
    # E-commerce/content work: funnel, product/detail, segment and tracing.
    "specialist": frozenset({"pheu", "chi-tiet", "phan-khuc", "truy-vet"}),
}


def allowed_paths(role: str) -> tuple[str, ...]:
    """Return the navigation-visible URL paths for a management role.

    Parameters
    ----------
    role : str
        One of the keys in ROLE_LABELS or "all".

    Returns
    -------
    tuple of str
        Paths in the global navigation order defined by PAGE_URLS.

    Raises
    ------
    ValueError
        If the role is not one of the four supported options.
    """
    if role == "all":
        return PAGE_URLS
    if role not in ROLE_PAGES:
        raise ValueError(f"Unknown management role: {role!r}")
    return tuple(path for path in PAGE_URLS if path in ROLE_PAGES[role])


def first_page(role: str) -> str:
    """Return the first visible page after changing to a role."""
    return allowed_paths(role)[0]
