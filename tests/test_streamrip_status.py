"""Tests for streamrip output classification.

These guard the fix for the misleading "Download complete!" shown when
streamrip exits 0 but the log contains track-level errors or a rejected
URL (observed during Deezer testing). The classifier is GTK-free so it
runs under plain ``pytest`` without importing the application module.
"""

from core import streamrip_status as s


# ── Per-line predicates ───────────────────────────────────────────────────

def test_line_says_finished_matches_banner():
    assert s.line_says_finished("All downloads finished!")
    assert s.line_says_finished("INFO  all downloads finished")
    assert not s.line_says_finished("Downloading track 1")


def test_line_is_error_catches_track_errors_and_tracebacks():
    assert s.line_is_error(
        "ERROR  Error downloading track: list index out of range")
    assert s.line_is_error("Error downloading track")
    assert s.line_is_error("Traceback (most recent call last):")
    assert s.line_is_error("ValueError: bad value")
    assert s.line_is_error("ContentTypeError: unexpected mimetype")
    assert s.line_is_error("UnicodeEncodeError: 'charmap' codec")
    assert s.line_is_error("Download failed")


def test_line_is_error_ignores_benign_summary():
    assert not s.line_is_error("Finished with 0 errors")
    assert not s.line_is_error("Downloading track 'Intro'")


def test_line_is_invalid_url_and_skip():
    assert s.line_is_invalid_url("Found invalid url: https://deezer.com/x")
    assert s.line_is_invalid_url("Invalid URL")
    assert s.line_is_skip("Skipping track (already exists)")
    assert not s.line_is_skip("Downloading track")


# ── Aggregate outcomes ────────────────────────────────────────────────────

def test_clean_run_is_success():
    out = "\n".join([
        "Downloading album 'Discovery'",
        "Track Download Done",
        "All downloads finished!",
    ])
    r = s.summarize(out, process_ok=True)
    assert r["outcome"] == s.SUCCESS
    assert r["finished"] is True
    assert r["error_count"] == 0


def test_finished_with_track_errors_is_partial():
    out = "\n".join([
        "Downloading album 'Discovery'",
        "ERROR  Error downloading track: list index out of range",
        "Error downloading track",
        "All downloads finished!",
    ])
    r = s.summarize(out, process_ok=True)
    assert r["outcome"] == s.PARTIAL
    assert r["finished"] is True
    assert r["error_count"] == 2


def test_skips_without_errors_still_partial_when_finished():
    out = "\n".join([
        "Skipping track 1 (already exists)",
        "All downloads finished!",
    ])
    r = s.summarize(out, process_ok=True)
    assert r["outcome"] == s.PARTIAL
    assert r["skip_count"] == 1
    assert r["error_count"] == 0


def test_invalid_url_without_finish_is_invalid_url():
    r = s.summarize("Found invalid url: https://deezer.com/page",
                     process_ok=False)
    assert r["outcome"] == s.INVALID_URL
    assert r["invalid_url"] is True


def test_errors_without_finish_is_failed():
    out = "\n".join([
        "Error downloading track",
        "Traceback (most recent call last):",
    ])
    r = s.summarize(out, process_ok=False)
    assert r["outcome"] == s.FAILED
    assert r["error_count"] >= 1


def test_process_ok_with_no_finish_marker_but_clean_is_success():
    r = s.summarize("Downloading album 'X'", process_ok=True)
    assert r["outcome"] == s.SUCCESS


def test_classify_outcome_direct_matrix():
    assert s.classify_outcome(
        finished=True, error_count=0, skip_count=0,
        invalid_url=False, process_ok=True) == s.SUCCESS
    assert s.classify_outcome(
        finished=True, error_count=3, skip_count=0,
        invalid_url=False, process_ok=True) == s.PARTIAL
    assert s.classify_outcome(
        finished=False, error_count=2, skip_count=0,
        invalid_url=False, process_ok=False) == s.FAILED
    assert s.classify_outcome(
        finished=False, error_count=0, skip_count=0,
        invalid_url=True, process_ok=False) == s.INVALID_URL
