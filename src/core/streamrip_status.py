"""Classify streamrip CLI output into an honest download outcome.

streamrip can exit ``0`` and still print ``All downloads finished!``
even when individual tracks failed (for example
``ERROR  Error downloading track: list index out of range``) or the
pasted URL was rejected (``Found invalid url``). Reporting that as
``Download complete!`` is misleading, so these helpers let the UI tell
a clean run apart from a partial / failed / rejected one.

Kept GTK-free and dependency-free so it can be unit-tested without
importing the application module.
"""

import re

# Per-track or fatal failure signatures.
ERROR_PATTERNS = (
    "error downloading track",
    "traceback",
    "download failed",
    "unicodeencodeerror",
    "valueerror",
    "contenttypeerror",
)

# The URL itself was not usable (landing page / redirect / typo).
INVALID_URL_PATTERNS = (
    "found invalid url",
    "invalid url",
)

# streamrip's end-of-run banner.
FINISHED_MARKER = "all downloads finished"

# Bare "ERROR" log-level token, e.g. streamrip prints "ERROR  ...".
# Excludes streamrip's harmless "0 errors" run summary.
_ERROR_TOKEN = re.compile(r"\berror\b")

# Outcomes.
SUCCESS = "success"          # finished cleanly, nothing errored/skipped
PARTIAL = "partial"          # finished but some tracks errored/skipped
FAILED = "failed"            # errors and no clean completion
INVALID_URL = "invalid_url"  # streamrip rejected the URL outright


def line_says_finished(line: str) -> bool:
    """True if the line is streamrip's completion banner."""
    return FINISHED_MARKER in line.lower()


def line_is_invalid_url(line: str) -> bool:
    """True if the line reports an invalid / unusable URL."""
    lo = line.lower()
    return any(p in lo for p in INVALID_URL_PATTERNS)


def line_is_skip(line: str) -> bool:
    """True if the line reports something being skipped."""
    return "skipping" in line.lower()


def line_is_error(line: str) -> bool:
    """True if the line signals a track-level or fatal error."""
    lo = line.lower()
    if any(p in lo for p in ERROR_PATTERNS):
        return True
    # Bare "ERROR" log level, but not the benign "0 errors" summary.
    return bool(_ERROR_TOKEN.search(lo)) and "0 errors" not in lo


def classify_outcome(*, finished: bool, error_count: int, skip_count: int,
                      invalid_url: bool, process_ok: bool) -> str:
    """Derive an overall outcome from accumulated signals.

    finished      streamrip printed its completion banner
    error_count   number of error lines observed
    skip_count    number of skip lines observed
    invalid_url   an invalid / redirected URL was reported
    process_ok    the streamrip process exited 0
    """
    if invalid_url and error_count == 0 and not finished:
        return INVALID_URL
    if finished or process_ok:
        if error_count or skip_count or invalid_url:
            return PARTIAL
        return SUCCESS
    return FAILED


def summarize(lines, process_ok: bool) -> dict:
    """Classify a string / iterable of output lines in one call.

    Returns a dict with: ``outcome``, ``finished``, ``error_count``,
    ``skip_count`` and ``invalid_url``. Convenience wrapper used by
    tests and any caller that has the full output buffered.
    """
    if isinstance(lines, str):
        lines = lines.splitlines()
    errors = skips = 0
    finished = invalid = False
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if line_says_finished(s):
            finished = True
        if line_is_invalid_url(s):
            invalid = True
            continue
        if line_is_skip(s):
            skips += 1
            continue
        if line_is_error(s):
            errors += 1
    outcome = classify_outcome(
        finished=finished, error_count=errors, skip_count=skips,
        invalid_url=invalid, process_ok=process_ok,
    )
    return {
        "outcome": outcome,
        "finished": finished,
        "error_count": errors,
        "skip_count": skips,
        "invalid_url": invalid,
    }
