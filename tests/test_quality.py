"""Tests for the service-aware quality layer (``core.quality``).

These guard the rule that Auryn must never write a quality value a music
service does not support: streamrip indexes a fixed per-service quality table
with the configured value and no bounds check, so an out-of-range value crashes
every track with ``list index out of range`` (Deezer is the worst case at
max 2). The module is GTK-free so these run under plain ``pytest`` without
importing the application module.
"""

from core import quality as q


# ── Per-service supported maximums ──────────────────────────────────────────

def test_service_max_quality_per_service():
    assert q.service_max_quality("deezer") == 2
    assert q.service_max_quality("qobuz") == 4
    assert q.service_max_quality("tidal") == 3
    assert q.service_max_quality("soundcloud") == 0


def test_unknown_service_uses_full_scale_and_does_not_clamp():
    # A source we don't have a ceiling for must keep working untouched.
    assert q.service_max_quality("napster") == q.MAX_QUALITY == 4
    assert q.clamp_quality("napster", 4) == 4
    assert q.quality_was_clamped("napster", 4) is False


def test_services_tuple_lists_every_known_service():
    assert set(q.SERVICES) == {"deezer", "qobuz", "tidal", "soundcloud"}


# ── Clamping ────────────────────────────────────────────────────────────────

def test_deezer_clamps_above_two():
    assert q.clamp_quality("deezer", 0) == 0
    assert q.clamp_quality("deezer", 2) == 2
    assert q.clamp_quality("deezer", 3) == 2  # FLAC 24/96+ — the crash trigger
    assert q.clamp_quality("deezer", 4) == 2  # Max (MQA)


def test_qobuz_keeps_full_high_quality_range():
    for level in range(0, 5):
        assert q.clamp_quality("qobuz", level) == level


def test_tidal_clamps_unsupported_max_to_hires():
    assert q.clamp_quality("tidal", 2) == 2
    assert q.clamp_quality("tidal", 3) == 3  # hi-res / MQA, the real ceiling
    assert q.clamp_quality("tidal", 4) == 3  # 4 is not a real TIDAL tier


def test_soundcloud_uses_safe_default():
    assert q.clamp_quality("soundcloud", 0) == 0
    assert q.clamp_quality("soundcloud", 2) == 0
    assert q.clamp_quality("soundcloud", 4) == 0


def test_clamp_handles_strings_negatives_and_garbage():
    assert q.clamp_quality("deezer", "3") == 2
    assert q.clamp_quality("qobuz", "4") == 4
    assert q.clamp_quality("deezer", -1) == 0
    assert q.clamp_quality("soundcloud", -5) == 0
    # Unparseable falls back to the (always-valid) service maximum.
    assert q.clamp_quality("deezer", None) == 2
    assert q.clamp_quality("deezer", "nonsense") == 2
    assert q.clamp_quality("qobuz", None) == 4


def test_quality_was_clamped_per_service():
    assert q.quality_was_clamped("deezer", 3) is True
    assert q.quality_was_clamped("deezer", 4) is True
    assert q.quality_was_clamped("deezer", 2) is False
    assert q.quality_was_clamped("qobuz", 4) is False
    assert q.quality_was_clamped("tidal", 4) is True
    assert q.quality_was_clamped("tidal", 3) is False
    assert q.quality_was_clamped("soundcloud", 1) is True
    assert q.quality_was_clamped("soundcloud", 0) is False
    # Garbage counts as "would change".
    assert q.quality_was_clamped("deezer", "nonsense") is True


# ── Labels ──────────────────────────────────────────────────────────────────

def test_quality_label_matches_ui_wording():
    assert q.quality_label(0) == "MP3 128"
    assert q.quality_label(1) == "MP3 320"
    assert q.quality_label(2) == "FLAC 16/44.1"
    assert q.quality_label(3) == "FLAC 24/96+"
    assert q.quality_label(4) == "Max (MQA)"
    assert q.quality_label("2") == "FLAC 16/44.1"
    # Out-of-scale / garbage degrades to a string instead of raising.
    assert q.quality_label(9) == "9"
    assert q.quality_label("nope") == "nope"


def test_labels_and_values_stay_aligned():
    assert len(q.QUALITY_LABELS) == len(q.QUALITY_VALUES) == 5
    assert q.QUALITY_VALUES == ["0", "1", "2", "3", "4"]


# ── Experimental tiers ──────────────────────────────────────────────────────

def test_tidal_hires_is_experimental():
    assert q.is_experimental("tidal", 3) is True
    assert q.is_experimental("tidal", 4) is True  # clamped to 3, still hi-res
    assert q.is_experimental("tidal", 2) is False


def test_other_services_are_not_experimental():
    assert q.is_experimental("deezer", 2) is False
    assert q.is_experimental("qobuz", 4) is False
    assert q.is_experimental("soundcloud", 0) is False
    assert q.is_experimental("unknown", 4) is False


# ── URL → service routing ───────────────────────────────────────────────────

def test_service_for_url_detects_each_service():
    assert q.service_for_url("https://www.deezer.com/album/302127") == "deezer"
    assert q.service_for_url("https://deezer.page.link/abc") == "deezer"
    assert q.service_for_url("https://link.deezer.com/s/abc") == "deezer"
    assert q.service_for_url("https://tidal.com/browse/album/1") == "tidal"
    assert q.service_for_url("https://listen.tidal.com/album/1") == "tidal"
    assert q.service_for_url("https://open.qobuz.com/album/abc") == "qobuz"
    assert q.service_for_url("https://soundcloud.com/artist/track") == "soundcloud"


def test_service_for_url_returns_none_for_unknown_or_empty():
    assert q.service_for_url("https://example.com/album/1") is None
    assert q.service_for_url("") is None
    assert q.service_for_url(None) is None


# ── User-facing clamp message ───────────────────────────────────────────────

def test_clamp_message_matches_required_wording():
    # The exact wording the task pins down for a downgraded Deezer download.
    assert q.clamp_message("deezer", 3) == (
        "Deezer supports up to FLAC 16/44.1; using FLAC 16/44.1.")
    assert q.clamp_message("deezer", 4) == (
        "Deezer supports up to FLAC 16/44.1; using FLAC 16/44.1.")


def test_clamp_message_per_service():
    assert q.clamp_message("tidal", 4) == (
        "TIDAL supports up to FLAC 24/96+; using FLAC 24/96+.")
    assert q.clamp_message("soundcloud", 3) == (
        "SoundCloud supports up to MP3 128; using MP3 128.")


# ── Cross-check: the Deezer wrapper delegates here ──────────────────────────

def test_deezer_helpers_delegate_to_central_logic():
    from core import deezer

    assert deezer.DEEZER_MAX_QUALITY == q.service_max_quality("deezer") == 2
    assert deezer.clamp_quality(4) == q.clamp_quality("deezer", 4) == 2
    assert deezer.quality_was_clamped(3) is True
    assert deezer.quality_label(2) == q.quality_label(2) == "FLAC 16/44.1"
