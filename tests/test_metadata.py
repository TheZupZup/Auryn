"""Regression tests for the protected album-metadata sidebar.

These cover the GTK-free parsing/sanitising layer in ``core.metadata``
that backs the right-side sidebar (cover + artist / album / quality /
track count / UPC / release date). The guarantee under test: partial,
``None``, or unexpectedly-shaped streaming-service payloads degrade to
empty values and NEVER raise — so the UI cannot crash on bad metadata.
"""

from core import metadata


# ── Text sanitising ──────────────────────────────────────────────────────

def test_sanitize_empty_and_falsy_values_return_empty():
    assert metadata.sanitize_meta_text("") == ""
    assert metadata.sanitize_meta_text(None) == ""
    assert metadata.sanitize_meta_text(0) == ""
    assert metadata.sanitize_meta_text("   ") == ""


def test_sanitize_strips_and_escapes_pango_markup():
    assert metadata.sanitize_meta_text("  Hello  ") == "Hello"
    assert metadata.sanitize_meta_text("A & B < C") == "A &amp; B &lt; C"


def test_sanitize_truncates_to_limit():
    assert metadata.sanitize_meta_text("x" * 50, limit=28) == "x" * 28
    assert metadata.sanitize_meta_text("x" * 50) == "x" * metadata.META_MAX_LEN


def test_build_meta_markup_wraps_or_returns_none():
    assert metadata.build_meta_markup("") is None
    assert metadata.build_meta_markup(None) is None
    assert metadata.build_meta_markup("Foo") == (
        '<span foreground="#e8e8e8" size="small">Foo</span>'
    )


def test_build_meta_markup_accepts_non_string_values():
    # Track counts arrive as ints from the API.
    assert metadata.build_meta_markup(14) == (
        '<span foreground="#e8e8e8" size="small">14</span>'
    )


# ── Deezer payload normalisation ──────────────────────────────────────────

def test_deezer_full_payload():
    data = {
        "artist": {"name": "Daft Punk"},
        "title": "Discovery",
        "nb_tracks": 14,
        "upc": "724384960650",
        "release_date": "2001-03-12",
        "cover_xl": "xl.jpg",
        "cover_big": "big.jpg",
    }
    f = metadata.deezer_album_fields(data)
    assert f["artist"] == "Daft Punk"
    assert f["album"] == "Discovery"
    assert f["total_tracks"] == 14
    assert f["upc"] == "724384960650"
    assert f["release_date"] == "2001-03-12"
    assert f["quality"] == "FLAC 16-bit / 44.1 kHz"
    assert f["cover_url"] == "xl.jpg"


def test_deezer_cover_precedence_falls_through_sizes():
    f = metadata.deezer_album_fields({"cover_medium": "m.jpg"})
    assert f["cover_url"] == "m.jpg"
    assert metadata.deezer_album_fields({})["cover_url"] == ""


def test_deezer_null_artist_does_not_raise():
    # Deezer occasionally returns an explicit null sub-object; the old
    # `data.get("artist", {}).get(...)` idiom would AttributeError here.
    f = metadata.deezer_album_fields({"artist": None, "title": "X"})
    assert f["artist"] == ""
    assert f["album"] == "X"


def test_deezer_handles_none_and_non_dict_input():
    for bad in (None, [], "oops", 42):
        f = metadata.deezer_album_fields(bad)
        assert f["artist"] == ""
        assert f["album"] == ""
        assert f["cover_url"] == ""
        # Constant quality string is always available for Deezer.
        assert f["quality"] == "FLAC 16-bit / 44.1 kHz"


# ── Qobuz payload normalisation ───────────────────────────────────────────

def test_qobuz_full_payload_hires():
    data = {
        "artist": {"name": "Air"},
        "title": "Moon Safari",
        "tracks_count": 10,
        "upc": "724384844820",
        "release_date_original": "1998-01-16T00:00:00",
        "maximum_sampling_rate": 96,
        "maximum_bit_depth": 24,
        "image": {"large": "https://cdn/x/cover_600.jpg"},
    }
    f = metadata.qobuz_album_fields(data)
    assert f["artist"] == "Air"
    assert f["album"] == "Moon Safari"
    assert f["total_tracks"] == 10
    assert f["release_date"] == "1998-01-16"
    assert f["quality"] == "FLAC 24-bit / 96 kHz"
    assert f["cover_url"] == "https://cdn/x/cover_max.jpg"
    assert f["cover_fallback"] == "https://cdn/x/cover_600.jpg"


def test_qobuz_artist_falls_back_to_performer():
    f = metadata.qobuz_album_fields(
        {"artist": None, "performer": {"name": "Performer X"}}
    )
    assert f["artist"] == "Performer X"


def test_qobuz_quality_branches():
    assert metadata.qobuz_album_fields(
        {"hires_streamable": True})["quality"] == "Hi-Res FLAC"
    # Neither sample-rate/bit-depth nor hires flag -> no quality (placeholder
    # is kept by the caller because the value is empty).
    assert metadata.qobuz_album_fields({})["quality"] == ""


def test_qobuz_tracks_count_key_present_wins_over_tracks_object():
    f = metadata.qobuz_album_fields(
        {"tracks_count": 12, "tracks": {"total": 99}}
    )
    assert f["total_tracks"] == 12


def test_qobuz_null_tracks_object_does_not_raise():
    # Old `data.get("tracks", {}).get("total")` would AttributeError when
    # the value is explicitly null.
    f = metadata.qobuz_album_fields({"tracks": None})
    assert f["total_tracks"] == ""


def test_qobuz_null_image_does_not_raise():
    f = metadata.qobuz_album_fields({"image": None})
    assert f["cover_url"] == ""
    assert f["cover_fallback"] == ""


def test_qobuz_release_date_non_string_is_coerced():
    f = metadata.qobuz_album_fields({"released_at": 1234567890})
    assert f["release_date"] == "1234567890"[:10]


def test_qobuz_handles_none_and_non_dict_input():
    for bad in (None, [], "oops", 42):
        f = metadata.qobuz_album_fields(bad)
        assert f["artist"] == ""
        assert f["album"] == ""
        assert f["quality"] == ""
        assert f["cover_url"] == ""
        assert f["cover_fallback"] == ""


# ── Track lists for the structured progress view ──────────────────────────

def test_deezer_album_tracks_normalises_titles_and_order():
    data = {
        "tracks": {"data": [
            {"title": "One More Time", "track_position": 1,
             "artist": {"name": "Daft Punk"}},
            {"title": "Aerodynamic", "track_position": 2,
             "artist": {"name": "Daft Punk"}},
        ]}
    }
    tracks = metadata.deezer_album_tracks(data)
    assert [t["title"] for t in tracks] == ["One More Time", "Aerodynamic"]
    assert [t["number"] for t in tracks] == [1, 2]
    assert tracks[0]["artist"] == "Daft Punk"


def test_deezer_album_tracks_falls_back_to_index_and_skips_empty():
    data = {"tracks": {"data": [
        {"title": "Has Title"},
        {"title": "", "artist": None},   # skipped (no title)
        {"artist": {"name": "X"}},        # skipped (no title)
    ]}}
    tracks = metadata.deezer_album_tracks(data)
    assert len(tracks) == 1
    assert tracks[0]["number"] == 1
    assert tracks[0]["artist"] == ""


def test_qobuz_album_tracks_uses_performer_then_album_artist():
    data = {
        "artist": {"name": "Air"},
        "tracks": {"items": [
            {"title": "La Femme d'Argent", "track_number": 1,
             "performer": {"name": "Air feat. X"}},
            {"title": "Sexy Boy", "track_number": 2},  # no performer
        ]},
    }
    tracks = metadata.qobuz_album_tracks(data)
    assert tracks[0]["artist"] == "Air feat. X"
    assert tracks[1]["artist"] == "Air"        # album-artist fallback
    assert [t["number"] for t in tracks] == [1, 2]


def test_track_lists_tolerate_none_and_bad_shapes():
    for bad in (None, [], "oops", 42, {"tracks": None}, {"tracks": "x"}):
        assert metadata.deezer_album_tracks(bad) == []
        assert metadata.qobuz_album_tracks(bad) == []
