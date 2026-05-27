"""Pure, GTK-free helpers for the right-side album metadata sidebar.

The sidebar (cover art + artist / album / quality / track count / UPC /
release date) is a protected, user-facing surface. The functions here own
all the *parsing* and *text sanitising* logic so it can be unit-tested
without GTK and so a malformed API payload can never crash the UI.

Mirrors the existing isolated-helper pattern used by ``core.status`` and
``core.errors``: dependency-free, side-effect-free, easy to test.

Important: these functions must stay tolerant of partial / ``None`` /
unexpectedly-shaped payloads. Streaming services occasionally return
``{"artist": null}`` or omit fields entirely; that must degrade to an
empty value, never an exception.
"""

import re

# Default visual truncation length for a sidebar value. Kept identical to
# the historical inline behaviour so the layout never shifts.
META_MAX_LEN = 30

# Color/markup for a populated metadata value (kept here so the one true
# style lives in one place, like core.status.build_status_markup).
_META_SPAN = '<span foreground="#e8e8e8" size="small">{}</span>'


def sanitize_meta_text(value, limit=META_MAX_LEN):
    """Return a Pango-safe, length-capped string for a metadata value.

    Returns ``""`` for falsy / empty values so callers can simply skip
    writing and leave the placeholder in place.
    """
    if not value:
        return ""
    txt = str(value).strip()
    if not txt:
        return ""
    return txt[:limit].replace("&", "&amp;").replace("<", "&lt;")


def build_meta_markup(value, limit=META_MAX_LEN):
    """Return ready-to-use Pango markup for *value*, or ``None`` if empty."""
    txt = sanitize_meta_text(value, limit)
    if not txt:
        return None
    return _META_SPAN.format(txt)


def _safe_dict(value):
    """Return *value* if it is a dict, otherwise an empty dict.

    Guards the very common ``data.get("artist", {}).get("name")`` idiom
    against an explicit ``"artist": null`` (where ``.get`` returns ``None``
    and the chained ``.get`` would raise ``AttributeError``).
    """
    return value if isinstance(value, dict) else {}


def deezer_album_fields(data):
    """Normalize a Deezer album payload into sidebar fields.

    Always returns a dict with every expected key present (empty string
    when unknown), regardless of how partial the input is.
    """
    data = _safe_dict(data)
    artist = _safe_dict(data.get("artist")).get("name", "") or ""
    return {
        "artist": artist,
        "album": data.get("title", "") or "",
        "total_tracks": data.get("nb_tracks", "") or "",
        "upc": data.get("upc", "") or "",
        "release_date": data.get("release_date", "") or "",
        # Deezer streams are reported as CD-quality FLAC by streamrip.
        "quality": "FLAC 16-bit / 44.1 kHz",
        "cover_url": (data.get("cover_xl")
                      or data.get("cover_big")
                      or data.get("cover_medium")
                      or ""),
    }


def qobuz_album_fields(data):
    """Normalize a Qobuz album payload into sidebar fields.

    Reproduces the historical field selection (artist→performer fallback,
    hi-res quality string, cover-size rewrite) but tolerates ``None`` /
    missing sub-objects so a sparse payload cannot raise.
    """
    data = _safe_dict(data)

    artist = (_safe_dict(data.get("artist")).get("name", "")
              or _safe_dict(data.get("performer")).get("name", "")
              or "")

    tracks = data.get("tracks_count", _safe_dict(data.get("tracks")).get("total", ""))

    raw_date = data.get("release_date_original") or data.get("released_at") or ""
    if not isinstance(raw_date, str):
        raw_date = str(raw_date)
    release_date = raw_date[:10]

    max_q = data.get("maximum_sampling_rate", 0)
    max_b = data.get("maximum_bit_depth", 0)
    if max_q and max_b:
        quality = f"FLAC {max_b}-bit / {max_q} kHz"
    elif data.get("hires_streamable"):
        quality = "Hi-Res FLAC"
    else:
        quality = ""

    img = _safe_dict(data.get("image"))
    raw_cover = img.get("large") or img.get("small") or img.get("thumbnail", "") or ""
    if raw_cover:
        cover_url = re.sub(r'_\d+\.jpg', '_max.jpg', raw_cover)
        cover_fallback = re.sub(r'_\d+\.jpg', '_600.jpg',
                                cover_url.replace('_max.jpg', '_600.jpg'))
    else:
        cover_url = ""
        cover_fallback = ""

    return {
        "artist": artist,
        "album": data.get("title", "") or "",
        "total_tracks": tracks or "",
        "upc": data.get("upc", "") or "",
        "release_date": release_date,
        "quality": quality,
        "cover_url": cover_url,
        "cover_fallback": cover_fallback,
    }


# ── Track lists for the structured progress view ──────────────────────────
#
# These feed core.download_session so the progress view can show real song
# titles in order before streamrip prints anything. Like the field helpers
# above they must tolerate partial / None / oddly-shaped payloads and always
# return a (possibly empty) list — never raise.

def _track_entry(number, title, artist):
    """Build one normalised track dict, or ``None`` if it has no title."""
    title = (str(title).strip() if title else "")
    if not title:
        return None
    return {
        "number": number,
        "title": title,
        "artist": (str(artist).strip() if artist else ""),
    }


def deezer_album_tracks(data):
    """Return ``[{number, title, artist}, ...]`` from a Deezer album payload.

    Deezer nests the track list under ``tracks -> data``. Missing / partial
    entries are skipped rather than raising, and the track position falls
    back to the list order when absent.
    """
    data = _safe_dict(data)
    items = _safe_dict(data.get("tracks")).get("data")
    if not isinstance(items, list):
        return []
    out = []
    for i, raw in enumerate(items):
        raw = _safe_dict(raw)
        number = raw.get("track_position") or (i + 1)
        artist = _safe_dict(raw.get("artist")).get("name", "") or ""
        entry = _track_entry(number, raw.get("title"), artist)
        if entry:
            out.append(entry)
    return out


def qobuz_album_tracks(data):
    """Return ``[{number, title, artist}, ...]`` from a Qobuz album payload.

    Qobuz nests the track list under ``tracks -> items`` with a
    ``performer`` per track (falling back to the album artist). Tolerant of
    partial / None entries.
    """
    data = _safe_dict(data)
    album_artist = (_safe_dict(data.get("artist")).get("name", "")
                    or _safe_dict(data.get("performer")).get("name", "")
                    or "")
    items = _safe_dict(data.get("tracks")).get("items")
    if not isinstance(items, list):
        return []
    out = []
    for i, raw in enumerate(items):
        raw = _safe_dict(raw)
        number = raw.get("track_number") or (i + 1)
        artist = (_safe_dict(raw.get("performer")).get("name", "")
                  or album_artist)
        entry = _track_entry(number, raw.get("title"), artist)
        if entry:
            out.append(entry)
    return out
