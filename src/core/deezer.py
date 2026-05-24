"""Deezer support helpers for Auryn.

Isolated, GTK-free, dependency-free logic that backs reliable Deezer
downloads through streamrip:

  * normalize & validate Deezer URLs exactly the way streamrip's URL parser
    expects them, so an unsupported link fails fast with guidance instead of
    a confusing mid-download crash,
  * clamp the requested download quality to Deezer's supported range — the
    root-cause fix for streamrip's repeated
    ``Error downloading track: list index out of range`` (streamrip indexes a
    three-row quality table with the configured quality, so any value above 2
    raises ``IndexError`` on *every* track),
  * inspect the streamrip-managed ``[deezer]`` config (ARL presence) without
    ever returning, logging or rendering the ARL,
  * classify Deezer-specific streamrip output into actionable categories.

Security invariant: no function in this module ever returns, logs, renders or
otherwise surfaces a raw ARL / session token. ARL state is reported only as
"present / missing".

Has no GTK / Auryn imports on purpose so it can be exercised by ``--doctor``
and unit tests without a display. Mirrors the isolated-helper pattern of
``core.tidal_auth``, ``core.metadata`` and ``core.streamrip_status``.
"""

import os
import re
import urllib.request

from core import quality as _quality

# streamrip's ``DeezerClient.max_quality`` (streamrip/client/deezer.py). The
# quality table there has exactly three rows — 0 = MP3 128, 1 = MP3 320,
# 2 = FLAC (CD quality) — and ``get_downloadable`` does ``quality_map[quality]``
# with no bounds check, so a configured quality of 3 or 4 raises
# ``IndexError: list index out of range`` for every track. The supported
# maximum and the clamping rule are defined once in :mod:`core.quality`.
DEEZER_MAX_QUALITY = _quality.service_max_quality("deezer")

# Stable, user-facing message for the streamrip provider crash. Defined once so
# the UI and the tests share a single wording.
PROVIDER_FAILURE_MESSAGE = (
    "Deezer provider failed while resolving/downloading tracks. "
    "Try another Deezer URL format or update streamrip."
)

# Auryn recommends Deezer: a large catalog and the simplest setup (a single ARL
# token, versus TIDAL's device-auth flow), which also suits the NAS/local-
# library workflow better than TIDAL auth. Surfaced in the UI so first-time
# users start with the service most likely to "just work". Wording lives here so
# the UI and the tests stay in sync.
RECOMMENDED = True
RECOMMENDED_LABEL = "Deezer (Recommended)"
RECOMMENDED_NOTE = (
    "Deezer is the recommended service for Auryn — a large catalog and the "
    "simplest setup: paste one ARL token and you're ready."
)


def url_guidance():
    """User-facing guidance for pasting Deezer URLs (shared by UI and tests).

    Returns a list of single-line strings. Never contains secrets.
    """
    return [
        "Prefer a direct deezer.com album, track or playlist URL "
        "(e.g. https://www.deezer.com/album/302127).",
        "If you have a link.deezer.com (or dzr.page.link) share link, open it "
        "in your browser and paste the final deezer.com URL it lands on.",
    ]

# URL classification kinds returned by :func:`classify_deezer_url`.
NOT_DEEZER = "not_deezer"      # not a Deezer URL at all
CONTENT = "content"            # canonical album/track/playlist/artist URL
PAGE_LINK = "page_link"        # deezer.page.link (streamrip resolves natively)
SHORT_LINK = "short_link"      # link.deezer.com / dzr.page.link (must resolve)
UNSUPPORTED = "unsupported"    # a deezer.com URL streamrip will not accept

# Error categories returned by :func:`classify_deezer_error`.
ERR_AUTH_MISSING = "auth_missing"
ERR_AUTH_INVALID = "auth_invalid"
ERR_UNSUPPORTED_URL = "unsupported_url"
ERR_PROVIDER_FAILURE = "provider_failure"
ERR_RATE_LIMIT = "rate_limit"
ERR_TRACK_FAILURE = "track_failure"


# Any Deezer-family host. Deliberately broad: it only gates whether
# Deezer-specific handling applies; the strict acceptance check is
# :func:`streamrip_will_accept`.
_DEEZER_HOST_RE = re.compile(
    r"(?:^|//|\.)(?:deezer\.com|deezer\.page\.link|link\.deezer\.com|"
    r"dzr\.page\.link)\b",
    re.I,
)

# A canonical Deezer content URL → captures (media_type, item_id). Tolerates
# any subdomain, an optional two-letter locale segment, and a trailing query
# string / fragment.
_CONTENT_RE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)?deezer\.com/(?:[a-z]{2}/)?"
    r"(album|artist|track|playlist)/(\d+)",
    re.I,
)

# streamrip's own native dynamic-link form (handled inside streamrip).
_PAGE_LINK_RE = re.compile(r"https?://deezer\.page\.link/\w+", re.I)

# Short / share links streamrip does NOT understand and that must be resolved
# to a canonical content URL before download.
_SHORT_LINK_RE = re.compile(
    r"https?://(?:link\.deezer\.com|dzr\.page\.link)/\S+", re.I
)

# Faithful mirror of streamrip's ``GenericURL.URL_REGEX`` (streamrip/rip/
# parse_url.py), used to validate that a final URL is one streamrip will
# actually accept. Group 1 = source, 2 = media_type, 3 = item_id — streamrip
# rejects the URL unless all three are present. Kept in sync with the installed
# streamrip; if streamrip later widens support the worst case is we fall back
# to its own "invalid url" handling, which Auryn already classifies.
_STREAMRIP_GENERIC_RE = re.compile(
    r"https?://(?:www|open|play|listen)?\.?(qobuz|tidal|deezer)\.com"
    r"(?:(?:/(album|artist|track|playlist|video|label))|(?:/[-\w]+?))+/([-\w]+)",
)

_SCHEME_RE = re.compile(r"[a-z][a-z0-9+.-]*://", re.I)
_BARE_HOST_RE = re.compile(
    r"(?:[a-z0-9-]+\.)?(?:deezer\.com|deezer\.page\.link|link\.deezer\.com|"
    r"dzr\.page\.link)/",
    re.I,
)


# ── Quality ────────────────────────────────────────────────────────────────

def clamp_quality(quality):
    """Clamp *quality* into Deezer's supported 0..2 range.

    Deezer-scoped wrapper over :func:`core.quality.clamp_quality`; kept for the
    Deezer-specific call sites and tests. This is the fix that prevents
    streamrip's ``list index out of range`` crash on Deezer.
    """
    return _quality.clamp_quality("deezer", quality)


def quality_was_clamped(quality):
    """True if :func:`clamp_quality` would change *quality*."""
    return _quality.quality_was_clamped("deezer", quality)


def quality_label(quality):
    """Human label for a Deezer quality level."""
    return _quality.quality_label(quality)


# ── URL handling ─────────────────────────────────────────────────────────────

def is_deezer_url(url):
    """True if *url* points at any Deezer-family host."""
    return bool(url) and bool(_DEEZER_HOST_RE.search(url))


def is_short_link(url):
    """True for a Deezer share link streamrip cannot open directly."""
    return bool(url) and bool(_SHORT_LINK_RE.match(url.strip()))


def _canonical_content_url(media_type, item_id):
    return "https://www.deezer.com/{}/{}".format(str(media_type).lower(),
                                                 item_id)


def normalize_deezer_url(url):
    """Pure (no-network) normalization of a pasted Deezer URL.

    * adds a missing ``https://`` scheme for a recognised Deezer host,
    * canonicalises a content URL to ``https://www.deezer.com/<type>/<id>``
      (dropping locale prefixes and tracking query strings) — a form both
      streamrip's parser and Auryn's metadata sidebar accept.

    Anything that is not a recognisable Deezer *content* URL (short links,
    page.link, non-Deezer) is returned with only the scheme fixed so the
    caller can resolve / validate it next. Never raises.
    """
    u = (url or "").strip()
    if not u:
        return u
    if not _SCHEME_RE.match(u) and _BARE_HOST_RE.match(u):
        u = "https://" + u
    m = _CONTENT_RE.search(u)
    if m:
        return _canonical_content_url(m.group(1), m.group(2))
    return u


def streamrip_will_accept(url):
    """True if streamrip's URL parser will accept *url* as a Deezer URL.

    Mirrors streamrip's ``GenericURL`` (all of source/media_type/item_id must
    be present) and its ``deezer.page.link`` dynamic-link matcher.
    """
    u = (url or "").strip()
    m = _STREAMRIP_GENERIC_RE.match(u)
    if m and all(m.group(i) for i in (1, 2, 3)) and m.group(1).lower() == "deezer":
        return True
    return bool(_PAGE_LINK_RE.match(u))


def classify_deezer_url(url):
    """Classify *url* for the download pre-check.

    Returns a dict with: ``kind`` (one of the module constants),
    ``media_type``, ``item_id``, ``normalized``, ``supported`` (streamrip will
    accept it as-is) and ``needs_resolution`` (a short link to resolve first).
    Pure / no network.
    """
    raw = (url or "").strip()
    result = {
        "kind": NOT_DEEZER,
        "media_type": None,
        "item_id": None,
        "normalized": raw,
        "supported": False,
        "needs_resolution": False,
    }
    if not is_deezer_url(raw):
        return result

    normalized = normalize_deezer_url(raw)
    result["normalized"] = normalized

    m = _CONTENT_RE.search(normalized)
    if m:
        result.update(kind=CONTENT, media_type=m.group(1).lower(),
                      item_id=m.group(2), supported=True)
        return result
    if _PAGE_LINK_RE.match(normalized):
        result.update(kind=PAGE_LINK, supported=True)
        return result
    if _SHORT_LINK_RE.match(normalized):
        result.update(kind=SHORT_LINK, needs_resolution=True)
        return result
    result.update(kind=UNSUPPORTED, supported=streamrip_will_accept(normalized))
    return result


def _default_opener(target, timeout):
    req = urllib.request.Request(target, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout)


def resolve_short_link(url, opener=None, timeout=8, max_bytes=200000):
    """Follow a Deezer share link to its canonical content URL.

    Returns ``(resolved_url_or_None, error_or_None)``. Network access goes
    through *opener* (injectable for tests); the default uses ``urllib`` with a
    browser User-Agent. This only follows the public redirect and, failing
    that, scans the public landing page for a deezer.com content URL — the same
    technique streamrip itself uses for ``deezer.page.link``. No authentication,
    no protected-content scraping and no DRM handling is involved. Never raises.
    """
    target = normalize_deezer_url(url)
    opener = opener or (lambda u: _default_opener(u, timeout))

    resp = None
    try:
        resp = opener(target)
    except Exception:
        return (None, "the share link could not be opened (network error)")

    try:
        final_url = ""
        try:
            final_url = resp.geturl() or ""
        except Exception:
            final_url = ""
        m = _CONTENT_RE.search(final_url)
        if m:
            return (normalize_deezer_url(final_url), None)

        body = ""
        try:
            raw = resp.read(max_bytes)
            body = (raw.decode("utf-8", "replace")
                    if isinstance(raw, (bytes, bytearray)) else str(raw))
        except Exception:
            body = ""
        m = _CONTENT_RE.search(body)
        if m:
            return (_canonical_content_url(m.group(1), m.group(2)), None)
        return (None,
                "the link did not resolve to a Deezer album/track/playlist URL")
    finally:
        try:
            resp.close()
        except Exception:
            pass


# ── Config detection ─────────────────────────────────────────────────────────

def read_deezer_section(cfg_path):
    """Best-effort read of the ``[deezer]`` table from ``config.toml``.

    Returns ``{key: value}`` (native types from tomllib, else strings) or
    ``{}`` on any problem. Never raises and never logs the values it reads.
    """
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    try:
        import tomllib  # stdlib on Python 3.11+

        sec = tomllib.loads(text).get("deezer")
        if isinstance(sec, dict):
            return dict(sec)
    except Exception:
        pass
    result = {}
    in_section = False
    for line in text.split("\n"):
        s = line.strip()
        m = re.match(r"\[([^\]]+)\]\s*$", s)
        if m:
            in_section = m.group(1).strip() == "deezer"
            continue
        if in_section:
            km = re.match(r'([A-Za-z0-9_]+)\s*=\s*"?(.*?)"?\s*$', s)
            if km:
                result[km.group(1)] = km.group(2)
    return result


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def deezer_config_status(cfg_path):
    """Return a structured, secret-free view of Deezer config readiness.

    Keys: ``config_exists``, ``section_readable``, ``arl_present``,
    ``quality`` (int or None), ``quality_in_range``, ``use_deezloader``
    (bool or None), ``problems`` (list of human strings) and ``ready``
    (True when streamrip has what it needs to authenticate Deezer).
    The ARL value itself is never returned.
    """
    status = {
        "config_exists": os.path.exists(cfg_path),
        "section_readable": False,
        "arl_present": False,
        "quality": None,
        "quality_in_range": True,
        "use_deezloader": None,
        "problems": [],
        "ready": False,
    }
    if not status["config_exists"]:
        status["problems"].append("streamrip config.toml not found.")
        return status

    sec = read_deezer_section(cfg_path)
    if not sec:
        status["problems"].append(
            "Could not read the [deezer] section from config.toml "
            "(missing or unparseable).")
        return status
    status["section_readable"] = True

    arl = sec.get("arl")
    status["arl_present"] = bool(arl is not None and str(arl).strip())

    raw_q = sec.get("quality")
    if raw_q is not None and str(raw_q).strip() != "":
        try:
            status["quality"] = int(str(raw_q).strip().strip('"'))
        except ValueError:
            status["quality"] = None
    if status["quality"] is not None:
        status["quality_in_range"] = 0 <= status["quality"] <= DEEZER_MAX_QUALITY

    status["use_deezloader"] = _as_bool(sec.get("use_deezloader"))

    if not status["arl_present"]:
        status["problems"].append(
            "No Deezer ARL is configured. streamrip needs an ARL cookie to "
            "authenticate Deezer downloads.")

    status["ready"] = status["arl_present"]
    return status


def deezer_setup_summary(cfg_path):
    """Offline, secret-free readiness check → ``(message, kind)``.

    Inspects only the saved config (no network, no download) and reports
    whether streamrip is configured for Deezer, never showing the ARL. Mirrors
    the offline ``Test TIDAL Connection`` behaviour. ``kind`` is one of
    ``ok`` / ``warn`` / ``info``.
    """
    st = deezer_config_status(cfg_path)
    if not st["config_exists"]:
        return ("streamrip config.toml not found — run `rip config reset` or "
                "open Setup first.", "warn")
    if not st["section_readable"]:
        return ("The [deezer] section is missing or unreadable in "
                "config.toml.", "warn")
    if not st["arl_present"]:
        return ("Deezer is not configured — no ARL found. Paste your ARL above "
                "and Save.", "warn")

    parts = ["ARL is configured (value hidden)"]
    if st["quality"] is not None:
        if st["quality_in_range"]:
            parts.append("quality {} ({})".format(
                st["quality"], quality_label(st["quality"])))
        else:
            parts.append("saved quality {} is out of range — Auryn will use {} "
                         "({}) for Deezer".format(
                             st["quality"], DEEZER_MAX_QUALITY,
                             quality_label(DEEZER_MAX_QUALITY)))
    return ("Deezer looks ready — " + ", ".join(parts) + ".", "ok")


# ── Error classification ───────────────────────────────────────────────────

def classify_deezer_error(text):
    """Classify a Deezer-related streamrip output line.

    Returns ``(category, friendly_message_or_None)``; ``(None, None)`` when the
    line is not a recognised Deezer error. Callers should scope this to a Deezer
    download (``is_deezer_url``) so a Qobuz/TIDAL line never triggers it, just
    like the TIDAL detectors in :mod:`core.tidal_auth`.
    """
    if not text:
        return (None, None)
    lo = text.lower()

    # The streamrip provider crash — check first because the same line also
    # contains "error downloading track".
    if "list index out of range" in lo:
        return (ERR_PROVIDER_FAILURE, PROVIDER_FAILURE_MESSAGE)

    if ("missingcredentialserror" in lo or "missing credentials" in lo
            or ("arl" in lo and any(p in lo for p in (
                "empty", "missing", "not set", "no arl", "required")))):
        return (ERR_AUTH_MISSING,
                "Deezer is not configured — add your ARL in Setup.")

    if (any(p in lo for p in ("invalid arl", "arl expired", "arl is invalid",
                              "bad arl", "wrong arl"))
            or ("deezer" in lo and "authenticationerror" in lo)
            or ("arl" in lo and "invalid" in lo)):
        return (ERR_AUTH_INVALID,
                "Deezer ARL is invalid or expired — update it in Setup.")

    if ("found invalid url" in lo or "invalid url" in lo
            or "unable to extract deezer dynamic link" in lo):
        return (ERR_UNSUPPORTED_URL,
                "Unsupported Deezer URL — paste a deezer.com album, track or "
                "playlist link.")

    if any(p in lo for p in ("connectionpool", "api.deezer.com",
                             "too many requests", "max retries",
                             "connection aborted", "connection reset",
                             "rate limit", "ratelimit", " 429")):
        return (ERR_RATE_LIMIT,
                "Deezer API rate-limit or network issue — wait a moment and "
                "retry.")

    if "error downloading track" in lo:
        return (ERR_TRACK_FAILURE, None)

    return (None, None)
