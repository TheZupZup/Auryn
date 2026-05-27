"""Tests for the GTK-free structured download session model.

These guard the behaviour the progress UI depends on: metadata seeds the
track list with real titles, streamrip lines advance per-track status,
the structured outcome agrees with core.streamrip_status, and a clean run
ends with every track Complete (so the UI never claims "complete" while
errors are present).
"""

from core import download_session as ds
from core import streamrip_status


class FakeClock:
    """Deterministic monotonic stand-in so elapsed times are testable."""

    def __init__(self):
        self.t = 0.0

    def tick(self, dt=1.0):
        self.t += dt

    def __call__(self):
        return self.t


def _meta(*titles):
    return [{"number": i + 1, "title": t, "artist": "Daft Punk"}
            for i, t in enumerate(titles)]


# ── Metadata-backed mode ──────────────────────────────────────────────────

def test_init_from_metadata_seeds_queued_tracks():
    s = ds.DownloadSession()
    s.init_from_metadata(_meta("One More Time", "Aerodynamic", "Digital Love"))
    assert s.metadata_backed is True
    assert [t.title for t in s.tracks] == [
        "One More Time", "Aerodynamic", "Digital Love"]
    assert all(t.status == ds.QUEUED for t in s.tracks)
    assert s.effective_total() == 3


def test_downloading_then_done_marks_tracks_complete_in_order():
    s = ds.DownloadSession()
    s.init_from_metadata(_meta("One More Time", "Aerodynamic"))

    s.feed_line("Downloading track 'One More Time'")
    assert s.tracks[0].status == ds.DOWNLOADING

    s.feed_line("Track Download Done")
    assert s.tracks[0].status == ds.COMPLETE
    assert s.tracks[1].status == ds.QUEUED

    s.feed_line("Downloading track 'Aerodynamic'")
    s.feed_line("Track Download Done")
    assert s.tracks[1].status == ds.COMPLETE
    assert s.completed_count == 2


def test_title_mismatch_still_advances_next_queued_row():
    # Metadata titles are trusted; a slightly different streamrip title must
    # not orphan progress — the next queued row advances instead.
    s = ds.DownloadSession()
    s.init_from_metadata(_meta("Track A", "Track B"))
    s.feed_line("Downloading track 'Something Else Entirely'")
    assert s.tracks[0].status == ds.DOWNLOADING
    assert s.tracks[0].title == "Track A"  # not renamed


def test_skip_and_error_are_counted_and_reflected():
    s = ds.DownloadSession()
    s.init_from_metadata(_meta("A", "B", "C"))

    s.feed_line("Skipping 'A' (already exists)")
    assert s.skip_count == 1
    assert s.tracks[0].status == ds.SKIPPED

    s.feed_line("Downloading track 'B'")
    s.feed_line("ERROR  Error downloading track: list index out of range")
    assert s.error_count == 1
    assert s.tracks[1].status == ds.ERROR


def test_speed_attaches_to_active_track():
    s = ds.DownloadSession()
    s.init_from_metadata(_meta("A"))
    s.feed_line("Downloading track 'A'")
    s.feed_line("progress 2.50 MB/s")
    assert s.tracks[0].speed == "2.50 MB/s"
    assert s.last_speed == "2.50 MB/s"


def test_elapsed_recorded_with_injected_clock():
    clock = FakeClock()
    s = ds.DownloadSession(clock=clock)
    s.init_from_metadata(_meta("A"))
    s.feed_line("Downloading track 'A'")
    clock.tick(4.0)
    s.feed_line("Track Download Done")
    assert s.tracks[0].elapsed == 4.0


# ── Parse-only fallback mode ──────────────────────────────────────────────

def test_parse_only_discovers_tracks_from_output():
    s = ds.DownloadSession()
    # No metadata -> parse-only. "Track N" then "Downloading <title>".
    s.feed_line("Track 1")
    s.feed_line("Downloading Good Life")
    assert s.metadata_backed is False
    assert len(s.tracks) == 1
    assert s.tracks[0].number == 1
    assert s.tracks[0].title == "Good Life"
    assert s.tracks[0].status == ds.DOWNLOADING

    s.feed_line("Track Download Done")
    assert s.tracks[0].status == ds.COMPLETE


def test_parse_only_total_hint_from_output():
    s = ds.DownloadSession()
    s.feed_line("Found 12 tracks")
    assert s.effective_total() == 12


# ── Outcome + finalisation ────────────────────────────────────────────────

def test_outcome_matches_streamrip_status_for_clean_run():
    s = ds.DownloadSession()
    s.init_from_metadata(_meta("A", "B"))
    s.feed_line("Downloading track 'A'")
    s.feed_line("Track Download Done")
    s.feed_line("Downloading track 'B'")
    s.feed_line("Track Download Done")
    s.feed_line("All downloads finished!")
    assert s.outcome(process_ok=True) == streamrip_status.SUCCESS
    assert s.has_problems() is False


def test_finalize_success_completes_all_rows():
    s = ds.DownloadSession()
    s.init_from_metadata(_meta("A", "B", "C"))
    s.feed_line("Downloading track 'A'")
    s.feed_line("Track Download Done")
    # B and C never got individual lines; a clean outcome completes them.
    s.finalize(streamrip_status.SUCCESS)
    assert all(t.status == ds.COMPLETE for t in s.tracks)


def test_finalize_partial_only_resolves_inflight_rows():
    s = ds.DownloadSession()
    s.init_from_metadata(_meta("A", "B", "C"))
    s.feed_line("Downloading track 'A'")
    s.feed_line("Track Download Done")        # A complete
    s.feed_line("Downloading track 'B'")      # B left mid-flight
    s.finalize(streamrip_status.PARTIAL)
    assert s.tracks[0].status == ds.COMPLETE
    assert s.tracks[1].status == ds.ERROR     # interrupted
    assert s.tracks[2].status == ds.QUEUED    # never started -> honest


def test_invalid_url_signal_recorded():
    s = ds.DownloadSession()
    s.feed_line("Found invalid url: https://deezer.com/page")
    assert s.invalid_url is True
    assert s.outcome(process_ok=False) == streamrip_status.INVALID_URL


def test_feed_line_never_raises_on_garbage():
    s = ds.DownloadSession()
    for bad in (None, "", "\x00\x01", "Downloading " + "x" * 5000):
        s.feed_line(bad)  # must not raise
