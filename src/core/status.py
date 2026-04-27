"""Status bar helpers: color mapping and markup builder."""

STATUS_COLORS = {
    "ok":    "#87a556",
    "error": "#e74c3c",
    "track": "#FF6B35",
    "info":  "#555555",
}


def build_status_markup(text: str, style: str = "info") -> str:
    """Return a Pango markup string for a status bar message."""
    color = STATUS_COLORS.get(style, "#555555")
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<span foreground="{color}" size="small">{safe}</span>'
