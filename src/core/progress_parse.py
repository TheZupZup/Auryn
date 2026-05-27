"""Pure, GTK-free extractors for streamrip progress lines.

The structured download view (``core.download_session``) is initialised
from resolved album/playlist metadata whenever possible, but it still has
to fall back to streamrip's raw stdout when no metadata is available
(playlists, single tracks, TIDAL / SoundCloud) or to track *which* item
streamrip is working on right now. The helpers here turn one cleaned
output line into a small structured signal without ever raising.

Design rules (mirrors ``core.streamrip_status`` / ``core.log_format``):
  * dependency-free and side-effect-free so it is unit-testable without
    importing the GTK application module,
  * every helper tolerates ``None`` / empty / unexpectedly-shaped input
    and returns ``None`` (or a falsy default) instead of raising,
  * extraction only — *classification* of done/skip/error/finished lines
    stays in ``core.streamrip_status`` so there is one source of truth.

These run on already-sanitised lines (ANSI / CR stripped by the output
pump), but they re-strip a leading log-level token defensively.
"""

import re

# Leading log-level / timestamp token streamrip prints, e.g.
# "INFO  Downloading ...", "DEBUG ...", "[12:00:00] ...". Stripped so the
# payload regexes below can anchor on the real message.
_LOG_PREFIX_RE = re.compile(
    r'^\s*(?:\[[^\]]*\]\s*)?(?:INFO|DEBUG|WARNING|WARN|ERROR|CRITICAL)?\s*',
    re.I,
)

# "Track Download Done" is streamrip's per-track completion marker. The
# existing output pump already keys the overall progress bar off it, so
# the structured model uses the same signal to stay consistent.
_TRACK_DONE_RE = re.compile(r'track\s+download\s+done', re.I)

# A standalone "Track 1" line (the track number, printed separately from
# the title). Must not match "Track Download Done" — the trailing anchor
# after the digits guards that.
_TRACK_NUM_RE = re.compile(r'^track\s+(\d+)\s*$', re.I)

# Transfer speed, e.g. "1.23 MB/s". Identical shape to the speed regex the
# output pump already uses for the footer indicator.
_SPEED_RE = re.compile(r'([\d.]+\s*[KMG]B/s)', re.I)

# Total-track count, kept deliberately strict so "Downloading track 1"
# (a space, not a colon) can never be misread as "1 track total".
_TOTAL_RE = (
    re.compile(r'\btracks?\s*[:=]\s*(\d+)', re.I),
    re.compile(r'\bfound\s+(\d+)\s+tracks?\b', re.I),
)

# Title extractors, most specific first.
_DL_TRACK_RE = re.compile(r'downloading\s+track\b[:\s]*(.+)', re.I)
_DL_GENERIC_RE = re.compile(r'downloading\s+(.+)', re.I)

# A title that is really just a position ("1", "1 of 12") is a number, not
# a song name — let the dedicated number line own it instead.
_NUMERIC_TITLE_RE = re.compile(r'^\d+(?:\s+of\s+\d+)?$', re.I)

# Trailing decorations streamrip appends to a "Downloading <title>" line:
# a run of box-drawing rule characters, or a "track.py:NNN" source ref.
_TRAILING_RULE_RE = re.compile(r'[\s\-—–─━]+$')
_TRACKPY_NOISE_RE = re.compile(r'\s+track\.py\b.*$', re.I)

# A run of 3+ rule characters marks a section banner (streamrip prints
# "Downloading <Album> ────────" for the album header) rather than a song.
_BANNER_RUN_RE = re.compile(r'[\-—–─━]{3,}')


def _strip_prefix(line):
    return _LOG_PREFIX_RE.sub('', line.rstrip('\n'), count=1)


def line_is_track_done(line):
    """True if *line* is streamrip's per-track completion marker."""
    if not line:
        return False
    return bool(_TRACK_DONE_RE.search(line))


def extract_speed(line):
    """Return a transfer-speed string (``"1.2 MB/s"``) or ``None``."""
    if not line:
        return None
    m = _SPEED_RE.search(line)
    return m.group(1).strip() if m else None


def extract_track_number(line):
    """Return the integer from a standalone ``"Track N"`` line, or ``None``."""
    if not line:
        return None
    m = _TRACK_NUM_RE.match(_strip_prefix(line).strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def extract_track_total(line):
    """Return a total-track count from a ``"Tracks: N"`` / ``"Found N tracks"``
    line, or ``None``. Strict on purpose so progress lines never match."""
    if not line:
        return None
    for rx in _TOTAL_RE:
        m = rx.search(line)
        if m:
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                return None
            return n if n > 0 else None
    return None


def _clean_title(raw):
    """Normalise the captured title fragment; return ``""`` if it is junk."""
    title = _TRACKPY_NOISE_RE.sub('', raw)
    title = _TRAILING_RULE_RE.sub('', title).strip()
    # Strip one layer of matching surrounding quotes.
    if len(title) >= 2 and title[0] in "\"'" and title[-1] == title[0]:
        title = title[1:-1].strip()
    if not title or len(title) > 200:
        return ""
    if "://" in title:
        return ""
    if _NUMERIC_TITLE_RE.match(title):
        return ""
    return title


def extract_track_title(line):
    """Return the song title from a ``"Downloading <title>"`` line, or ``None``.

    Handles ``Downloading track 'Title'``, ``Downloading track Title`` and
    the bare ``Downloading Title`` form. Album / playlist banner lines and
    pure track-number lines are rejected so only real song titles come
    back.
    """
    if not line:
        return None
    s = _strip_prefix(line).strip()
    if not s:
        return None
    lo = s.lower()
    if lo.startswith(("downloading album", "downloading playlist")):
        return None
    # "Downloading <Album> ────────" is the album header banner, not a song.
    if _BANNER_RUN_RE.search(s):
        return None

    m = _DL_TRACK_RE.search(s)
    if m:
        title = _clean_title(m.group(1))
        return title or None

    m = _DL_GENERIC_RE.search(s)
    if m:
        title = _clean_title(m.group(1))
        return title or None
    return None


def normalize_title(value):
    """Return a comparison-friendly form of a title for matching.

    Lowercases, trims, collapses internal whitespace and drops surrounding
    quotes / trailing punctuation so a streamrip title and a metadata title
    that differ only cosmetically still match.
    """
    if not value:
        return ""
    txt = str(value).strip().lower()
    if len(txt) >= 2 and txt[0] in "\"'" and txt[-1] == txt[0]:
        txt = txt[1:-1].strip()
    txt = re.sub(r'\s+', ' ', txt)
    return txt.strip(" .'\"")
