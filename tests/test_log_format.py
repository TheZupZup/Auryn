"""Tests for the GTK-free log sanitisation and error-summary helpers.

These guard the readability fixes added on top of streamrip's raw output:
control-character sanitisation, soft-wrapping of pathological single
tokens, and the user-facing summary surfaced above the log when a
download finishes with errors.

GTK-free so it runs under plain ``pytest`` without importing the
application module.
"""

from core import log_format as lf


# ── sanitize_log_text ─────────────────────────────────────────────────

def test_sanitize_empty_returns_empty():
    assert lf.sanitize_log_text("") == ""
    assert lf.sanitize_log_text(None) == ""


def test_sanitize_preserves_newlines_and_tabs():
    src = "line1\n\tindented\nline3\n"
    assert lf.sanitize_log_text(src) == src


def test_sanitize_strips_ansi_csi_and_osc():
    src = "\x1b[31mERROR\x1b[0m something \x1b]0;title\x07 trailing"
    out = lf.sanitize_log_text(src)
    assert "ERROR" in out
    assert "something" in out
    assert "trailing" in out
    assert "\x1b" not in out


def test_sanitize_drops_bare_control_bytes_but_keeps_text():
    src = "Error\x00 downloading\x07 track\x01 'Hello'"
    out = lf.sanitize_log_text(src)
    assert out == "Error downloading track 'Hello'"


def test_sanitize_drops_solo_cr_keeps_crlf_pair():
    src = "progress\r50%\r\ndone\n"
    out = lf.sanitize_log_text(src)
    # \r before non-newline removed; \r\n kept as \r\n (then preserved as-is).
    assert "\r50%" not in out
    assert "50%" in out
    assert "done" in out


def test_sanitize_replaces_replacement_char_visibly():
    out = lf.sanitize_log_text("track � name")
    assert "?" in out
    assert "�" not in out


def test_sanitize_preserves_unicode_emoji_and_paths():
    src = "✅  Saved /home/user/Music/Café/01 — Track.flac\n"
    assert lf.sanitize_log_text(src) == src


# ── wrap_long_line ────────────────────────────────────────────────────

def test_wrap_short_line_unchanged():
    assert lf.wrap_long_line("short line", width=80) == "short line"


def test_wrap_breaks_on_whitespace_when_possible():
    line = "word " * 40  # ~200 chars of word-spaces
    out = lf.wrap_long_line(line, width=40)
    for piece in out.split("\n"):
        assert len(piece) <= 40


def test_wrap_hard_breaks_unbreakable_token():
    long_path = "/very/long/path/" + "x" * 200
    out = lf.wrap_long_line(long_path, width=50)
    pieces = out.split("\n")
    assert len(pieces) >= 4
    for piece in pieces:
        assert len(piece) <= 50


def test_wrap_preserves_existing_newlines():
    src = "line1 is short\n" + "x" * 200 + "\nline3"
    out = lf.wrap_long_line(src, width=50)
    assert out.startswith("line1 is short\n")
    assert out.endswith("\nline3")


def test_prepare_for_display_combines_sanitize_and_wrap():
    src = "\x1b[31m" + ("x" * 200) + "\x1b[0m"
    out = lf.prepare_for_display(src, width=50)
    assert "\x1b" not in out
    for piece in out.split("\n"):
        assert len(piece) <= 50


# ── count_error_patterns / build_error_summary ────────────────────────

def test_count_error_patterns_empty_returns_zero_counts():
    counts = lf.count_error_patterns("")
    assert all(v == 0 for v in counts.values())
    assert "track_errors" in counts


def test_count_error_patterns_recognises_all_signatures():
    log = "\n".join([
        "ERROR  Error downloading track: list index out of range",
        "ERROR  Error downloading track 'Foo'",
        "Found invalid url: https://x",
        "Skipping 'already-exists.flac'",
        "Traceback (most recent call last):",
        "UnicodeEncodeError: 'charmap' codec",
        "ContentTypeError: unexpected mimetype",
    ])
    counts = lf.count_error_patterns(log)
    assert counts["track_errors"] == 2
    assert counts["list_index_errors"] == 1
    assert counts["invalid_urls"] == 1
    assert counts["skips"] == 1
    assert counts["tracebacks"] == 1
    assert counts["unicode_errors"] == 1
    assert counts["content_type_errors"] == 1


def test_count_does_not_double_count_multi_line_traceback():
    log = "\n".join([
        "Traceback (most recent call last):",
        '  File "x.py", line 1, in <module>',
        "    raise ValueError('bad')",
        "ValueError: bad",
    ])
    counts = lf.count_error_patterns(log)
    assert counts["tracebacks"] == 1


def test_build_error_summary_returns_empty_when_clean():
    counts = lf.count_error_patterns("")
    assert lf.build_error_summary(
        counts, error_count=0, skip_count=0, invalid_url=False) == ""


def test_build_error_summary_headline_matches_requirement_example():
    counts = lf.count_error_patterns(
        "Error downloading track\n" * 16)
    summary = lf.build_error_summary(
        counts, error_count=16, skip_count=0, invalid_url=False,
        metadata_loaded=True)
    assert summary.startswith(
        "Download finished with errors: 16 track errors detected.")
    assert "Metadata and cover were loaded" in summary


def test_build_error_summary_pluralises_correctly():
    counts = lf.count_error_patterns("Error downloading track\n")
    summary = lf.build_error_summary(
        counts, error_count=1, skip_count=1, invalid_url=False)
    assert "1 track error detected" in summary
    assert "1 track skipped" in summary


def test_build_error_summary_lists_pattern_breakdown():
    log = "\n".join([
        "ERROR  Error downloading track: list index out of range",
        "ERROR  Error downloading track 'Foo'",
        "Skipping 'a'",
        "Skipping 'b'",
    ])
    counts = lf.count_error_patterns(log)
    summary = lf.build_error_summary(
        counts, error_count=2, skip_count=2, invalid_url=False)
    assert "Detected patterns:" in summary
    assert "2 track download errors" in summary
    assert "2 skipped items" in summary
    assert "1 list-index-out-of-range" in summary


def test_summarize_log_one_shot():
    log = "\n".join([
        "Error downloading track",
        "Traceback (most recent call last):",
    ])
    summary = lf.summarize_log(
        log, error_count=2, skip_count=0, invalid_url=False)
    assert summary.startswith("Download finished with errors")
    assert "1 track download error" in summary
    assert "1 traceback" in summary


def test_summarize_log_invalid_url_only():
    summary = lf.summarize_log(
        "Found invalid url: https://x",
        error_count=0, skip_count=0, invalid_url=True)
    assert "URL rejected by streamrip" in summary
