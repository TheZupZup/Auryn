"""Tests for the GTK-free Deezer support layer (``core.deezer``).

These guard the fixes for the Deezer download failures observed during
testing — chiefly the repeated
``ERROR  Error downloading track: list index out of range``, whose root cause
is a configured quality above Deezer's supported maximum (streamrip indexes a
three-row quality table). They also cover URL normalization / validation,
secret-free config detection and error classification.

The module is GTK-free so these run under plain ``pytest`` without importing
the application module.
"""

import os
import textwrap

from core import deezer as d


# ── Quality clamping (the root-cause fix) ──────────────────────────────────

def test_clamp_quality_passes_supported_values():
    assert d.clamp_quality(0) == 0
    assert d.clamp_quality(1) == 1
    assert d.clamp_quality(2) == 2


def test_clamp_quality_lowers_out_of_range_values():
    # 3 (FLAC 24/96+) and 4 (Max/MQA) are exactly what crashed streamrip.
    assert d.clamp_quality(3) == d.DEEZER_MAX_QUALITY == 2
    assert d.clamp_quality(4) == 2


def test_clamp_quality_handles_strings_and_garbage():
    assert d.clamp_quality("3") == 2
    assert d.clamp_quality("2") == 2
    assert d.clamp_quality(-1) == 0
    assert d.clamp_quality(None) == 2
    assert d.clamp_quality("nonsense") == 2


def test_quality_was_clamped():
    assert d.quality_was_clamped(3) is True
    assert d.quality_was_clamped(4) is True
    assert d.quality_was_clamped(2) is False
    assert d.quality_was_clamped(0) is False


# ── URL detection / normalization ───────────────────────────────────────────

def test_is_deezer_url():
    assert d.is_deezer_url("https://www.deezer.com/album/123")
    assert d.is_deezer_url("https://deezer.page.link/abc")
    assert d.is_deezer_url("https://link.deezer.com/s/abc")
    assert not d.is_deezer_url("https://tidal.com/album/123")
    assert not d.is_deezer_url("https://notdeezer.example.com/x")
    assert not d.is_deezer_url("")


def test_normalize_adds_scheme():
    assert d.normalize_deezer_url("www.deezer.com/album/123") == (
        "https://www.deezer.com/album/123")
    assert d.normalize_deezer_url("deezer.com/track/9").startswith("https://")


def test_normalize_canonicalises_locale_and_query():
    assert d.normalize_deezer_url(
        "https://www.deezer.com/en/album/302127?utm_source=share"
    ) == "https://www.deezer.com/album/302127"
    assert d.normalize_deezer_url(
        "https://deezer.com/fr/track/3135556"
    ) == "https://www.deezer.com/track/3135556"


def test_normalize_leaves_short_and_page_links_alone_except_scheme():
    assert d.normalize_deezer_url("https://deezer.page.link/xyz") == (
        "https://deezer.page.link/xyz")
    assert d.normalize_deezer_url("link.deezer.com/s/abc") == (
        "https://link.deezer.com/s/abc")


# ── streamrip acceptance contract ───────────────────────────────────────────

def test_streamrip_will_accept_matches_supported_forms():
    assert d.streamrip_will_accept("https://www.deezer.com/album/302127")
    assert d.streamrip_will_accept("https://www.deezer.com/en/track/3135556")
    assert d.streamrip_will_accept("https://deezer.com/playlist/12")
    assert d.streamrip_will_accept("https://deezer.page.link/abcDEF")


def test_streamrip_will_not_accept_unsupported_forms():
    # streamrip's dynamic-link matcher only knows deezer.page.link.
    assert not d.streamrip_will_accept("https://link.deezer.com/s/abc123")
    assert not d.streamrip_will_accept("https://dzr.page.link/abc123")
    # No media type / id.
    assert not d.streamrip_will_accept("https://www.deezer.com/profile/me")
    assert not d.streamrip_will_accept("not a url")


# ── URL classification ───────────────────────────────────────────────────────

def test_classify_content_url():
    info = d.classify_deezer_url("https://www.deezer.com/en/album/302127")
    assert info["kind"] == d.CONTENT
    assert info["media_type"] == "album"
    assert info["item_id"] == "302127"
    assert info["normalized"] == "https://www.deezer.com/album/302127"
    assert info["supported"] is True
    assert info["needs_resolution"] is False


def test_classify_page_link_is_supported_native():
    info = d.classify_deezer_url("https://deezer.page.link/abc")
    assert info["kind"] == d.PAGE_LINK
    assert info["supported"] is True
    assert info["needs_resolution"] is False


def test_classify_short_link_needs_resolution():
    for url in ("https://link.deezer.com/s/abc123",
                "https://dzr.page.link/xyz"):
        info = d.classify_deezer_url(url)
        assert info["kind"] == d.SHORT_LINK
        assert info["needs_resolution"] is True
        assert info["supported"] is False


def test_classify_non_deezer():
    info = d.classify_deezer_url("https://tidal.com/album/1")
    assert info["kind"] == d.NOT_DEEZER


# ── Short-link resolution (injected opener, no network) ──────────────────────

class _FakeResp:
    def __init__(self, final_url="", body=""):
        self._final = final_url
        self._body = body.encode("utf-8")

    def geturl(self):
        return self._final

    def read(self, *_):
        return self._body

    def close(self):
        pass


def test_resolve_short_link_via_final_url():
    resolved, err = d.resolve_short_link(
        "https://link.deezer.com/s/abc",
        opener=lambda u: _FakeResp(
            final_url="https://www.deezer.com/en/album/302127"))
    assert err is None
    assert resolved == "https://www.deezer.com/album/302127"


def test_resolve_short_link_via_body_scan():
    html = '<a href="https://www.deezer.com/fr/track/3135556">x</a>'
    resolved, err = d.resolve_short_link(
        "https://link.deezer.com/s/abc",
        opener=lambda u: _FakeResp(final_url="https://link.deezer.com/landing",
                                   body=html))
    assert err is None
    assert resolved == "https://www.deezer.com/track/3135556"


def test_resolve_short_link_failure_returns_error():
    resolved, err = d.resolve_short_link(
        "https://link.deezer.com/s/abc",
        opener=lambda u: _FakeResp(final_url="https://example.com/nope",
                                   body="no deezer link here"))
    assert resolved is None
    assert err


def test_resolve_short_link_network_error_is_caught():
    def boom(_u):
        raise OSError("network down")

    resolved, err = d.resolve_short_link("https://link.deezer.com/s/abc",
                                         opener=boom)
    assert resolved is None
    assert err


# ── Config detection (never leaks the ARL) ──────────────────────────────────

def _write_cfg(tmp_path, body):
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


def test_config_status_missing_file(tmp_path):
    st = d.deezer_config_status(str(tmp_path / "nope.toml"))
    assert st["config_exists"] is False
    assert st["ready"] is False
    assert st["problems"]


def test_config_status_no_arl(tmp_path):
    cfg = _write_cfg(tmp_path, '''
        [deezer]
        arl = ""
        quality = 2
    ''')
    st = d.deezer_config_status(cfg)
    assert st["section_readable"] is True
    assert st["arl_present"] is False
    assert st["ready"] is False


def test_config_status_with_arl_and_quality(tmp_path):
    cfg = _write_cfg(tmp_path, '''
        [deezer]
        arl = "SECRET_ARL_VALUE"
        quality = 2
        use_deezloader = true
    ''')
    st = d.deezer_config_status(cfg)
    assert st["arl_present"] is True
    assert st["ready"] is True
    assert st["quality"] == 2
    assert st["quality_in_range"] is True
    assert st["use_deezloader"] is True
    # The ARL value must never appear anywhere in the returned structure.
    assert "SECRET_ARL_VALUE" not in repr(st)


def test_config_status_flags_out_of_range_quality(tmp_path):
    cfg = _write_cfg(tmp_path, '''
        [deezer]
        arl = "x"
        quality = 4
    ''')
    st = d.deezer_config_status(cfg)
    assert st["quality"] == 4
    assert st["quality_in_range"] is False


def test_setup_summary_messages(tmp_path):
    missing = d.deezer_setup_summary(str(tmp_path / "no.toml"))
    assert missing[1] == "warn"

    cfg_no_arl = _write_cfg(tmp_path, '[deezer]\narl = ""\nquality = 2\n')
    msg, kind = d.deezer_setup_summary(cfg_no_arl)
    assert kind == "warn"
    assert "not configured" in msg.lower()

    cfg_ok = _write_cfg(tmp_path, '[deezer]\narl = "tok"\nquality = 2\n')
    msg, kind = d.deezer_setup_summary(cfg_ok)
    assert kind == "ok"
    assert "tok" not in msg  # never echo the ARL


# ── Error classification ───────────────────────────────────────────────────

def test_classify_list_index_is_provider_failure():
    cat, msg = d.classify_deezer_error(
        "ERROR  Error downloading track: list index out of range")
    assert cat == d.ERR_PROVIDER_FAILURE
    assert msg == d.PROVIDER_FAILURE_MESSAGE


def test_classify_auth_missing_and_invalid():
    cat, _ = d.classify_deezer_error("raise MissingCredentialsError")
    assert cat == d.ERR_AUTH_MISSING
    cat, _ = d.classify_deezer_error("Invalid arl, try again.")
    assert cat == d.ERR_AUTH_INVALID


def test_classify_unsupported_url_and_rate_limit():
    cat, _ = d.classify_deezer_error("Found invalid url: https://x")
    assert cat == d.ERR_UNSUPPORTED_URL
    cat, _ = d.classify_deezer_error(
        "WARNING urllib3.connectionpool api.deezer.com retrying")
    assert cat == d.ERR_RATE_LIMIT


def test_classify_plain_track_failure_and_none():
    cat, msg = d.classify_deezer_error(
        "Error downloading track: something else")
    assert cat == d.ERR_TRACK_FAILURE
    assert msg is None
    assert d.classify_deezer_error("Downloading track 'Intro'") == (None, None)
    assert d.classify_deezer_error("") == (None, None)


# ── Recommended-service treatment ───────────────────────────────────────────

def test_recommended_flag_and_label():
    assert d.RECOMMENDED is True
    assert "Recommended" in d.RECOMMENDED_LABEL
    assert d.RECOMMENDED_LABEL.startswith("Deezer")


def test_recommended_note_is_single_line_and_secret_free():
    assert d.RECOMMENDED_NOTE
    assert "\n" not in d.RECOMMENDED_NOTE
    assert "arl" not in d.RECOMMENDED_NOTE.lower() or "ARL token" in d.RECOMMENDED_NOTE


def test_url_guidance_covers_direct_and_share_links():
    lines = d.url_guidance()
    assert isinstance(lines, list) and len(lines) >= 2
    joined = " ".join(lines).lower()
    # Prefer a direct deezer.com URL …
    assert "deezer.com" in joined
    # … and explain the share-link → browser → final-URL workaround.
    assert "link.deezer.com" in joined
    assert "browser" in joined
    # Guidance must stay single-line per entry (rendered as bullet list).
    for line in lines:
        assert "\n" not in line


# ── Sanity: module constants are stable ─────────────────────────────────────

def test_provider_failure_message_is_actionable():
    assert "Deezer provider failed" in d.PROVIDER_FAILURE_MESSAGE
    assert "update streamrip" in d.PROVIDER_FAILURE_MESSAGE
    assert os.linesep not in d.PROVIDER_FAILURE_MESSAGE  # single-line status
