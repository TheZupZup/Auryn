"""Status bar helpers: color mapping and markup builder."""

# "track" is Auryn's sea-glass jade accent; keep it in sync with ACCENT in
# Auryn.py (this is a GTK-free core module, so the value is mirrored here).
STATUS_COLORS = {
    "ok":    "#87a556",
    "error": "#e74c3c",
    "track": "#55BA9B",
    "info":  "#555555",
}


def build_status_markup(text: str, style: str = "info") -> str:
    """Return a Pango markup string for a status bar message."""
    color = STATUS_COLORS.get(style, "#555555")
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<span foreground="{color}" size="small">{safe}</span>'
