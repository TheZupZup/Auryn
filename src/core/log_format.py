"""GTK-free helpers for sanitising and summarising streamrip output.

The download log can contain extremely long lines (file paths, URLs,
tracebacks), mojibake from a misencoded subprocess pipe, or stray ANSI /
control bytes. The display widget keeps the raw text available, but the
readability issues hurt diagnostics, so the helpers here:

  * strip / replace unsafe control characters without destroying paths
    or error messages,
  * soft-wrap pathologically long single tokens so the GTK view does
    not scroll horizontally forever,
  * categorise common streamrip failure signatures so the UI can show
    a short, human-readable summary above the raw log.

Mirrors the isolated, dependency-free pattern of ``core.status``,
``core.errors``, ``core.metadata`` and ``core.streamrip_status`` so it
can be unit-tested without importing the GTK application module.
"""

import re
import unicodedata


# Newline + tab are the only C0 controls we want to keep — they carry
# real layout meaning. Everything else in the C0 / C1 range is stripped.
_ALLOWED_C0 = {"\n", "\t"}

# CSI / OSC escape sequences that may slip through the existing ANSI
# strip in the streamrip output pump (it only handles a subset).
_ANSI_CSI_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')
_ANSI_OSC_RE = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')
_BARE_ESC_RE = re.compile(r'\x1b')

# A solo \r inside a line collapses the cursor to column 0 in a real
# terminal, but in a GTK TextView it shows up as a stray glyph.
_CR_NOT_NL_RE = re.compile(r'\r(?!\n)')


def sanitize_log_text(text):
    """Return *text* with display-hostile characters removed or replaced.

    Preserves newlines, tabs and the visible payload of every line
    (paths, error messages, URLs) so the sanitised output still mirrors
    the original line structure and remains copy-able.
    """
    if not text:
        return ""
    s = text if isinstance(text, str) else str(text)

    s = _ANSI_CSI_RE.sub('', s)
    s = _ANSI_OSC_RE.sub('', s)
    s = _BARE_ESC_RE.sub('', s)
    s = _CR_NOT_NL_RE.sub('', s)

    out = []
    for ch in s:
        if ch in _ALLOWED_C0:
            out.append(ch)
            continue
        cp = ord(ch)
        if cp < 0x20 or cp == 0x7F:
            continue
        if 0x80 <= cp <= 0x9F:
            continue
        # U+FFFD usually means upstream decoding already failed — keep a
        # visible mark instead of a silent gap so users can spot a bad
        # encoding cluster.
        if ch == '�':
            out.append('?')
            continue
        # Zero-width / format characters confuse line wrapping and copy.
        if unicodedata.category(ch) == 'Cf':
            continue
        out.append(ch)
    return ''.join(out)


# ── Parse-time line cleanup ───────────────────────────────────────────
#
# The download / TIDAL-login output pumps strip a small, fixed set of
# terminal escapes from each raw streamrip line *before* matching it for
# progress / title / speed signals, so the parsing regexes anchor on the
# real message. This is intentionally lighter than sanitize_log_text (the
# fuller display-time pass that still runs afterwards): it only removes
# the SGR-colour / cursor CSI sequences with a final byte in "mGKHF", OSC
# sequences terminated by BEL, and carriage returns. Defined once here so
# the three pumps share a single implementation instead of re-coding it.
_STREAM_CSI_RE = re.compile(r'\x1b\[[0-9;]*[mGKHF]')
_STREAM_OSC_RE = re.compile(r'\x1b\][^\x07]*\x07')


def clean_stream_line(line):
    """Strip terminal colour/cursor escapes and carriage returns from *line*.

    Returns the cleaned line (without altering its newline, if any) so the
    progress parsers see plain text. Tolerates ``None`` / non-string input
    by returning ``""`` rather than raising, so a pump can never crash on a
    malformed read.
    """
    if not line:
        return ""
    s = line if isinstance(line, str) else str(line)
    s = _STREAM_CSI_RE.sub('', s)
    s = _STREAM_OSC_RE.sub('', s)
    return s.replace('\r', '')


# Soft-wrap width tuned to the visible columns of the log panel at the
# default window size. GTK's own word-wrap handles paragraphs with
# whitespace; this helper exists for unbroken paths / URLs / traceback
# repr strings where GTK has nothing to break on.
DEFAULT_WRAP_WIDTH = 110


def wrap_long_line(text, width=DEFAULT_WRAP_WIDTH):
    """Soft-wrap each line in *text* whose length exceeds *width*.

    Prefers a whitespace break in the right half of the window so we do
    not produce single-word fragments; falls back to a hard break so an
    unbroken URL/path still wraps. Newlines in the input are preserved,
    so calling this on a multi-line chunk yields a multi-line result.
    """
    if not text or width <= 0:
        return text
    pieces = []
    for raw in text.split('\n'):
        if len(raw) <= width:
            pieces.append(raw)
            continue
        current = raw
        wrapped = []
        while len(current) > width:
            break_at = current.rfind(' ', max(width // 2, 1), width)
            if break_at <= 0:
                break_at = width
            wrapped.append(current[:break_at].rstrip())
            current = current[break_at:].lstrip()
        if current:
            wrapped.append(current)
        pieces.append('\n'.join(wrapped))
    return '\n'.join(pieces)


def prepare_for_display(text, width=DEFAULT_WRAP_WIDTH):
    """Convenience wrapper: sanitize, then soft-wrap.

    Used by the GTK log view so a single helper covers both display
    fixes. Returns ``""`` for empty input so the caller can skip insert.
    """
    return wrap_long_line(sanitize_log_text(text), width=width)


# ── Error summarisation ───────────────────────────────────────────────

# Patterns the user-facing summary breaks down by. Ordered most-specific
# first so a more informative match wins when a line could match several
# generic patterns (e.g. a "list index out of range" inside a track
# error line is also counted as a track error elsewhere — these counts
# are independent, not exclusive, by design).
_SUMMARY_PATTERNS = (
    ("track_errors",        re.compile(r"error downloading track", re.I)),
    ("list_index_errors",   re.compile(r"list index out of range", re.I)),
    ("invalid_urls",        re.compile(r"(found invalid url|invalid url)", re.I)),
    ("unicode_errors",      re.compile(r"unicodeencodeerror",      re.I)),
    ("content_type_errors", re.compile(r"contenttypeerror",        re.I)),
    ("skips",               re.compile(r"\bskipping\b",            re.I)),
    ("tracebacks",          re.compile(r"^traceback\b",            re.I)),
)

_PATTERN_LABELS = {
    "track_errors":        "track download error",
    "list_index_errors":   "list-index-out-of-range",
    "invalid_urls":        "invalid URL",
    "unicode_errors":      "UnicodeEncodeError",
    "content_type_errors": "ContentTypeError",
    "skips":               "skipped item",
    "tracebacks":          "traceback",
}


def count_error_patterns(text):
    """Return a dict ``pattern_key -> line_count`` for *text*.

    Counts lines, not regex matches, so a single multi-line traceback
    contributes one ``tracebacks`` hit and not one per frame.
    """
    counts = {key: 0 for key, _ in _SUMMARY_PATTERNS}
    if not text:
        return counts
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for key, rx in _SUMMARY_PATTERNS:
            if rx.search(line):
                counts[key] += 1
    return counts


def build_error_summary(counts, *, error_count, skip_count,
                         invalid_url, metadata_loaded=False):
    """Return the multi-line summary surfaced above the raw log.

    *counts* is the dict from :func:`count_error_patterns`.
    *error_count* / *skip_count* / *invalid_url* come from the existing
    :mod:`core.streamrip_status` tallies so the summary stays consistent
    with the rest of the UI. Returns ``""`` when nothing went wrong.
    """
    if not (error_count or skip_count or invalid_url):
        return ""

    head_parts = []
    if error_count:
        head_parts.append(
            f"{error_count} track error{'s' if error_count != 1 else ''} detected")
    if skip_count:
        head_parts.append(
            f"{skip_count} track{'s' if skip_count != 1 else ''} skipped")
    if invalid_url and not error_count and not skip_count:
        head_parts.append("URL rejected by streamrip")
    elif invalid_url:
        head_parts.append("URL flagged as invalid")

    headline = "Download finished with errors: " + ", ".join(head_parts) + "."

    parts = [headline]
    if metadata_loaded:
        parts.append(
            "Metadata and cover were loaded, but one or more tracks failed.")

    breakdown = []
    for key, _ in _SUMMARY_PATTERNS:
        n = counts.get(key, 0)
        if not n:
            continue
        label = _PATTERN_LABELS[key]
        breakdown.append(f"  - {n} {label}{'s' if n != 1 else ''}")
    if breakdown:
        parts.append("Detected patterns:")
        parts.extend(breakdown)

    return "\n".join(parts)


def summarize_log(text, *, error_count, skip_count, invalid_url,
                   metadata_loaded=False):
    """One-shot helper: classify *text* and build the human summary.

    Useful for callers that have already buffered the whole log; the GTK
    side uses :func:`count_error_patterns` + :func:`build_error_summary`
    directly so it can pass the same counts to other code paths.
    """
    counts = count_error_patterns(text)
    return build_error_summary(
        counts,
        error_count=error_count,
        skip_count=skip_count,
        invalid_url=invalid_url,
        metadata_loaded=metadata_loaded,
    )
