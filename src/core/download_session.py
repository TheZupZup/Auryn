"""GTK-free structured model for a single download's per-track progress.

Auryn historically showed only streamrip's raw terminal output while a
download ran. This module backs the new structured progress view: an
honest, scannable list of tracks with a status, a result and (when
available) a transfer speed / elapsed time — without ever touching the
streamrip download pipeline itself.

It is intentionally observational:

  * It is *initialised* from the album / playlist metadata Auryn already
    resolves for the sidebar (real song titles, in order), and otherwise
    falls back to parsing streamrip stdout via :mod:`core.progress_parse`.
  * It is *fed* the same cleaned output lines the GTK log pump already
    emits, so it adds zero new subprocess handling.
  * It reuses :mod:`core.streamrip_status` for done / skip / error /
    finished classification so the structured outcome can never disagree
    with the headline outcome the rest of the UI computes.

Kept dependency-free (apart from sibling ``core`` modules) and free of
GTK so it can be unit-tested without the application module.
"""

import time

from core import progress_parse
from core import streamrip_status


# Per-track statuses surfaced in the structured view.
QUEUED = "Queued"
DOWNLOADING = "Downloading"
COMPLETE = "Complete"
SKIPPED = "Skipped"
ERROR = "Error"

_TERMINAL = (COMPLETE, SKIPPED, ERROR)


class TrackProgress:
    """One row in the structured download view.

    All fields are plain data; the GTK layer reads them to render / update
    a row and never the other way around.
    """

    def __init__(self, number, title, artist=""):
        self.number = number
        self.title = (title or "").strip()
        self.artist = (artist or "").strip()
        self.status = QUEUED
        self.speed = ""
        self.detail = ""          # short result / error text
        self.started = None       # clock() value when it went Downloading
        self.finished = None      # clock() value when it reached a terminal
        self.elapsed = None       # seconds (float) once finished
        self._seq = 0             # start-order tie-breaker for concurrency

    @property
    def is_terminal(self):
        return self.status in _TERMINAL


class DownloadSession:
    """Accumulates per-track progress for one download.

    Two modes, chosen automatically:

    * **Metadata-backed** — :meth:`init_from_metadata` seeds the real track
      list up front; streamrip lines then only *advance* statuses.
    * **Parse-only** — no metadata was available, so tracks are discovered
      from ``Downloading <title>`` lines as the download proceeds.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.tracks = []
        self.metadata_backed = False
        self.total_hint = 0           # parsed "N tracks" total (fallback)
        self.completed_count = 0      # streamrip "Track Download Done" count
        self.error_count = 0
        self.skip_count = 0
        self.invalid_url = False
        self.finished_marker = False
        self.last_speed = ""
        self._start_seq = 0           # ordering for "oldest downloading"
        self._last_seen_number = None  # from a standalone "Track N" line
        self._finalized = False

    # ── Initialisation ────────────────────────────────────────────────

    def init_from_metadata(self, track_dicts):
        """Seed the track list from resolved album/playlist metadata.

        *track_dicts* is the list produced by ``core.metadata`` helpers:
        ``[{"number": int, "title": str, "artist": str}, ...]``. Tolerant
        of an empty / ``None`` list (leaves the session in parse-only mode).
        """
        if not track_dicts:
            return
        self.tracks = []
        for i, td in enumerate(track_dicts):
            td = td if isinstance(td, dict) else {}
            number = td.get("number") or (i + 1)
            self.tracks.append(
                TrackProgress(number, td.get("title", ""),
                              td.get("artist", "")))
        self.metadata_backed = bool(self.tracks)
        if self.metadata_backed:
            self.total_hint = len(self.tracks)

    # ── Derived values for the UI ─────────────────────────────────────

    def effective_total(self):
        """Best estimate of the total track count."""
        return max(self.total_hint, len(self.tracks))

    def overall_fraction(self):
        """Completed fraction in ``0.0..1.0`` for an overall progress bar."""
        total = self.effective_total()
        if total <= 0:
            return 0.0
        return min(self.completed_count / total, 1.0)

    def counts(self):
        """Return a snapshot of the tallies the summary banner needs."""
        done = sum(1 for t in self.tracks if t.status == COMPLETE)
        return {
            "total": self.effective_total(),
            "complete": done,
            "skipped": sum(1 for t in self.tracks if t.status == SKIPPED),
            "errors": sum(1 for t in self.tracks if t.status == ERROR),
            "downloading": sum(1 for t in self.tracks
                               if t.status == DOWNLOADING),
            # Raw streamrip-signal tallies (independent of per-track mapping)
            # so the banner stays honest even in parse-only mode.
            "done_signals": self.completed_count,
            "error_signals": self.error_count,
            "skip_signals": self.skip_count,
        }

    def has_problems(self):
        """True if any error / skip / invalid-URL signal was observed."""
        return bool(self.error_count or self.skip_count or self.invalid_url)

    def outcome(self, process_ok):
        """Classify the run exactly like the rest of the UI does."""
        return streamrip_status.classify_outcome(
            finished=self.finished_marker,
            error_count=self.error_count,
            skip_count=self.skip_count,
            invalid_url=self.invalid_url,
            process_ok=process_ok,
        )

    # ── Internal track-state transitions ──────────────────────────────

    def _active_index(self):
        """Most recently started still-Downloading track, or ``None``."""
        best = None
        best_seq = -1
        for i, t in enumerate(self.tracks):
            if t.status == DOWNLOADING and t._seq > best_seq:
                best, best_seq = i, t._seq
        return best

    def _oldest_downloading(self):
        best = None
        best_seq = None
        for i, t in enumerate(self.tracks):
            if t.status == DOWNLOADING and (best_seq is None
                                            or t._seq < best_seq):
                best, best_seq = i, t._seq
        return best

    def _first_non_terminal(self):
        for i, t in enumerate(self.tracks):
            if not t.is_terminal:
                return i
        return None

    def _begin(self, i):
        t = self.tracks[i]
        t.status = DOWNLOADING
        t.started = self._clock()
        self._start_seq += 1
        t._seq = self._start_seq

    def _terminate(self, i, status, detail=""):
        t = self.tracks[i]
        t.status = status
        if detail:
            t.detail = detail
        t.finished = self._clock()
        if t.started is not None and t.finished is not None:
            t.elapsed = max(0.0, t.finished - t.started)

    # ── Line feed ─────────────────────────────────────────────────────

    def feed_line(self, line):
        """Update the model from one cleaned streamrip output line.

        Returns the set of track indices whose row needs re-rendering (a
        newly discovered track's index is included so the UI can append a
        row). Never raises.
        """
        changed = set()
        if not line:
            return changed
        try:
            return self._feed_line(line, changed)
        except Exception:
            # The structured view is a best-effort overlay; a parsing edge
            # case must never break the log pump that drives the download.
            return changed

    def _feed_line(self, line, changed):
        if streamrip_status.line_says_finished(line):
            self.finished_marker = True
        if streamrip_status.line_is_invalid_url(line):
            self.invalid_url = True
            return changed
        self._absorb_metrics(line, changed)
        return self._absorb_event(line, changed)

    def _absorb_metrics(self, line, changed):
        """Soak up non-terminal signals: track total, number and speed."""
        if not self.metadata_backed:
            total = progress_parse.extract_track_total(line)
            if total and total > self.total_hint:
                self.total_hint = total
            number = progress_parse.extract_track_number(line)
            if number is not None:
                self._last_seen_number = number
        speed = progress_parse.extract_speed(line)
        if speed:
            self.last_speed = speed
            i = self._active_index()
            if i is not None:
                self.tracks[i].speed = speed
                changed.add(i)

    def _absorb_event(self, line, changed):
        """Apply at most one state transition (skip / done / error / start).

        Order mirrors core.streamrip_status: skip before error so a
        "Skipping ..." line is never miscounted as an error.
        """
        if streamrip_status.line_is_skip(line):
            self.skip_count += 1
            self._resolve_one(SKIPPED, "Skipped", changed, prefer_active=True)
            return changed
        if progress_parse.line_is_track_done(line):
            self.completed_count += 1
            self._resolve_one(COMPLETE, "Done", changed, prefer_active=False)
            return changed
        if streamrip_status.line_is_error(line):
            self.error_count += 1
            i = self._active_index()
            if i is not None:
                self._terminate(i, ERROR, "Error")
                changed.add(i)
            return changed
        title = progress_parse.extract_track_title(line)
        if title:
            i = self._note_downloading(title)
            if i is not None:
                changed.add(i)
        return changed

    def _resolve_one(self, status, detail, changed, *, prefer_active):
        """Move one in-flight (or next pending) track to a terminal *status*.

        ``prefer_active`` picks the most recently started track (skips, which
        usually concern the line just announced); otherwise the oldest
        downloading one is completed first (FIFO under concurrency).
        """
        i = self._active_index() if prefer_active else self._oldest_downloading()
        if i is None:
            i = self._first_non_terminal()
        if i is not None:
            if status == COMPLETE:
                self.tracks[i].speed = ""
            self._terminate(i, status, detail)
            changed.add(i)

    def _note_downloading(self, title):
        """Mark the track matching *title* as Downloading; return its index."""
        norm = progress_parse.normalize_title(title)

        if self.metadata_backed:
            # Prefer an exact, still-queued title match; otherwise advance
            # the next queued row without renaming (titles already trusted).
            for i, t in enumerate(self.tracks):
                if (t.status == QUEUED
                        and progress_parse.normalize_title(t.title) == norm):
                    self._begin(i)
                    return i
            i = self._first_queued()
            if i is not None:
                self._begin(i)
                return i
            return None

        # Parse-only mode: reuse an existing non-terminal row for this
        # title, else discover a new track.
        for i, t in enumerate(self.tracks):
            if (not t.is_terminal
                    and progress_parse.normalize_title(t.title) == norm):
                if t.status != DOWNLOADING:
                    self._begin(i)
                return i
        number = (self._last_seen_number
                  if self._last_seen_number is not None
                  else len(self.tracks) + 1)
        self._last_seen_number = None
        track = TrackProgress(number, title)
        self.tracks.append(track)
        i = len(self.tracks) - 1
        self._begin(i)
        return i

    def _first_queued(self):
        for i, t in enumerate(self.tracks):
            if t.status == QUEUED:
                return i
        return None

    # ── Finalisation ──────────────────────────────────────────────────

    def finalize(self, outcome):
        """Reconcile non-terminal rows once the download has ended.

        Returns the set of changed indices. Conservative on purpose: a
        clean run completes every row, while any other outcome only resolves
        rows that were left mid-flight (Downloading) — queued rows that were
        never confirmed stay Queued rather than being claimed done.
        """
        self._finalized = True
        changed = set()
        if outcome == streamrip_status.SUCCESS:
            for i, t in enumerate(self.tracks):
                if not t.is_terminal:
                    self._terminate(i, COMPLETE, "Done")
                    changed.add(i)
        else:
            for i, t in enumerate(self.tracks):
                if t.status == DOWNLOADING:
                    self._terminate(i, ERROR, "Interrupted")
                    changed.add(i)
        return changed
