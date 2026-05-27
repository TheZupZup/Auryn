"""Tests for the GTK-free streamrip progress-line extractors.

These back the structured download view's parse-only fallback, so they
guard that real song titles are pulled out while album banners, numbers
and source-ref noise are rejected — and that nothing ever raises.
"""

from core import progress_parse as p


# ── Title extraction ──────────────────────────────────────────────────────

def test_extract_title_quoted_and_unquoted_track_forms():
    assert p.extract_track_title("Downloading track 'Good Life'") == "Good Life"
    assert p.extract_track_title('Downloading track "Good Life"') == "Good Life"
    assert p.extract_track_title("Downloading track Good Life") == "Good Life"


def test_extract_title_bare_downloading_form():
    # The raw output the issue describes: "Downloading Good Life".
    assert p.extract_track_title("Downloading Good Life") == "Good Life"


def test_extract_title_strips_log_prefix_and_trackpy_noise():
    assert p.extract_track_title(
        "INFO  Downloading track 'Aerodynamic' track.py:212") == "Aerodynamic"
    assert p.extract_track_title(
        "[12:00:01] Downloading track 'Veridis Quo'") == "Veridis Quo"


def test_extract_title_rejects_album_and_playlist_banners():
    assert p.extract_track_title("Downloading album 'Discovery'") is None
    assert p.extract_track_title("Downloading playlist 'Road Trip'") is None
    # "Downloading <Album> ────────" header form.
    assert p.extract_track_title("Downloading Discovery ────────────") is None


def test_extract_title_rejects_numbers_urls_and_empty():
    assert p.extract_track_title("Downloading 1") is None
    assert p.extract_track_title("Downloading track 1 of 12") is None
    assert p.extract_track_title("Downloading https://x/y") is None
    assert p.extract_track_title("Nothing relevant here") is None


def test_extract_title_never_raises_on_bad_input():
    assert p.extract_track_title(None) is None
    assert p.extract_track_title("") is None


# ── Track number / done / speed / total ───────────────────────────────────

def test_extract_track_number_only_standalone_lines():
    assert p.extract_track_number("Track 1") == 1
    assert p.extract_track_number("  track 12  ") == 12
    assert p.extract_track_number("Track Download Done") is None
    assert p.extract_track_number("Track 3: Aerodynamic") is None


def test_line_is_track_done():
    assert p.line_is_track_done("Track Download Done")
    assert p.line_is_track_done("INFO  track download done")
    assert not p.line_is_track_done("Downloading track 'x'")
    assert not p.line_is_track_done(None)


def test_extract_speed():
    assert p.extract_speed("downloading at 1.23 MB/s now") == "1.23 MB/s"
    assert p.extract_speed("512 KB/s") == "512 KB/s"
    assert p.extract_speed("no speed here") is None


def test_extract_track_total_is_strict():
    assert p.extract_track_total("Tracks: 14") == 14
    assert p.extract_track_total("Found 9 tracks") == 9
    # A "Downloading track 1" line must not be read as a total of 1.
    assert p.extract_track_total("Downloading track 1") is None
    assert p.extract_track_total("Tracks: 0") is None


# ── Normalisation ─────────────────────────────────────────────────────────

def test_normalize_title_matches_cosmetic_differences():
    assert p.normalize_title("  'Good   Life' ") == "good life"
    assert p.normalize_title("Good Life.") == "good life"
    assert p.normalize_title(None) == ""
    assert (p.normalize_title("Aerodynamic")
            == p.normalize_title("aerodynamic"))
