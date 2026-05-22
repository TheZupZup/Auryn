"""Service-aware download-quality helpers for Auryn.

streamrip exposes a single 0–4 quality scale, but each music service only
implements part of it. Writing a value above a service's real maximum makes
streamrip index its fixed quality table out of bounds and crash
(``Error downloading track: list index out of range``) on *every* track — most
visibly for Deezer, whose table has only three rows (0..2).

This module is the single source of truth for "what quality is each service
allowed to use", so the clamping rules are defined once instead of being
duplicated across the UI, the Deezer helper and the streamrip-config writer.
Selecting a quality a service cannot provide is downgraded *cleanly* (clamped
to the service maximum) with a clear log message rather than failing the
download.

GTK-free and dependency-free on purpose so it can be exercised by ``--doctor``
and unit tests without a display, mirroring the isolated-helper pattern of
``core.deezer`` / ``core.tidal_auth`` / ``core.metadata``.
"""

import re

# streamrip's universal quality scale (``quality = N`` in config.toml):
#   0 = MP3/AAC 128 kbps
#   1 = MP3/AAC 320 kbps
#   2 = FLAC 16 bit / 44.1 kHz (CD / lossless)
#   3 = FLAC 24 bit / <=96 kHz (hi-res)
#   4 = FLAC 24 bit / <=192 kHz (Qobuz "max")
# These are the canonical, user-facing names; the GTK quality selector uses the
# same wording (see Auryn.ui) so the picker and the log messages never drift.
QUALITY_LABELS = ["MP3 128", "MP3 320", "FLAC 16/44.1", "FLAC 24/96+", "Max (MQA)"]
QUALITY_VALUES = ["0", "1", "2", "3", "4"]

MIN_QUALITY = 0
MAX_QUALITY = len(QUALITY_VALUES) - 1  # 4 — absolute ceiling of the scale

# Per-service support on the scale above.
#   ``max``               highest quality streamrip accepts for the service;
#                         higher selections are clamped down to it.
#   ``experimental_from`` quality at/above which the tier is flaky/experimental
#                         in streamrip (currently only TIDAL hi-res), else None.
#
# Deezer    : its quality table has 3 rows (0..2); >2 raises IndexError on every
#             track — the root-cause crash this module exists to prevent.
# Qobuz     : full range 0..4 (keeps Auryn's current high-quality behaviour).
# TIDAL     : tops out at hi-res/MQA (3); 4 is not a real TIDAL tier, and the
#             hi-res tier is treated as experimental.
# SoundCloud: a single ~128 kbps stream (0); higher values are meaningless.
_SERVICES = {
    "deezer":     {"display": "Deezer",     "max": 2, "experimental_from": None},
    "qobuz":      {"display": "Qobuz",      "max": 4, "experimental_from": None},
    "tidal":      {"display": "TIDAL",      "max": 3, "experimental_from": 3},
    "soundcloud": {"display": "SoundCloud", "max": 0, "experimental_from": None},
}

# The streamrip config sections Auryn writes a quality into, in a stable order.
SERVICES = tuple(_SERVICES.keys())

# Host-based service detection for quality routing/logging. Deliberately broad
# (covers share / dynamic-link hosts) and independent of the metadata-oriented
# ``detect_service_and_id`` in the GTK module.
_HOST_PATTERNS = (
    ("deezer", re.compile(
        r"(?:deezer\.com|deezer\.page\.link|link\.deezer\.com|dzr\.page\.link)",
        re.I)),
    ("tidal", re.compile(r"(?:listen\.|play\.)?tidal\.com", re.I)),
    ("qobuz", re.compile(r"(?:open\.|play\.)?qobuz\.com", re.I)),
    ("soundcloud", re.compile(r"(?:on\.|m\.)?soundcloud\.com", re.I)),
)


def service_max_quality(service):
    """Highest quality value streamrip accepts for *service*.

    Unknown services fall back to the full scale (no clamping) so a new
    streamrip source keeps working until its real ceiling is added here.
    """
    return _SERVICES.get(service, {}).get("max", MAX_QUALITY)


def service_display_name(service):
    """Human, correctly-cased service name (e.g. ``"TIDAL"``)."""
    info = _SERVICES.get(service)
    if info:
        return info["display"]
    return service.title() if service else "This service"


def _to_int(quality):
    return int(str(quality).strip())


def clamp_quality(service, quality):
    """Clamp *quality* into the range *service* actually supports.

    Accepts ints or numeric strings; anything unparseable falls back to the
    service maximum (a safe, always-valid upper bound). This is the fix that
    stops streamrip's ``list index out of range`` crash on Deezer and prevents
    the equivalent out-of-range writes for the other services.
    """
    ceiling = service_max_quality(service)
    try:
        q = _to_int(quality)
    except (TypeError, ValueError):
        return ceiling
    if q < MIN_QUALITY:
        return MIN_QUALITY
    if q > ceiling:
        return ceiling
    return q


def quality_was_clamped(service, quality):
    """True if :func:`clamp_quality` would change *quality* for *service*."""
    try:
        return _to_int(quality) != clamp_quality(service, quality)
    except (TypeError, ValueError):
        return True


def quality_label(quality):
    """Human label for a quality value on the universal scale."""
    try:
        q = _to_int(quality)
    except (TypeError, ValueError):
        return str(quality)
    if MIN_QUALITY <= q < len(QUALITY_LABELS):
        return QUALITY_LABELS[q]
    return str(q)


def is_experimental(service, quality):
    """True if the (clamped) quality is a flaky/experimental tier for *service*.

    Currently only TIDAL's hi-res/MQA tier; used to surface a gentle note
    without blocking or downgrading the download.
    """
    threshold = _SERVICES.get(service, {}).get("experimental_from")
    if threshold is None:
        return False
    return clamp_quality(service, quality) >= threshold


def service_for_url(url):
    """Best-effort music service for *url* (for quality routing/logging).

    Returns one of the keys in :data:`SERVICES`, or ``None``. Host-based and
    pure; complements the metadata-oriented detector in the GTK module.
    """
    u = (url or "").strip()
    if not u:
        return None
    for service, pattern in _HOST_PATTERNS:
        if pattern.search(u):
            return service
    return None


def clamp_message(service, requested):
    """User-facing note when *requested* is lowered for *service*.

    Example::

        Deezer supports up to FLAC 16/44.1; using FLAC 16/44.1.
    """
    used = clamp_quality(service, requested)
    return "{} supports up to {}; using {}.".format(
        service_display_name(service),
        quality_label(service_max_quality(service)),
        quality_label(used))
