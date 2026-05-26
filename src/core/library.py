"""Pure, GTK-free helpers for organising downloads into a tidy music library.

After streamrip finishes a download, Auryn can reorganise the files into a
predictable NAS / Jellyfin / Symfonium-friendly layout:

    Music/<Album Artist>/<Album Title>/<Quality>/NN. <Artist> - <Title>.<ext>
                                                 cover.jpg

    Music/Playlists/<Playlist Name>/NN. <Artist> - <Title>.<ext>
                                    playlist.m3u
                                    cover.jpg

This module owns *only* the name/path computation and the move *planning*. It
performs no file I/O, no GTK and no network, so every rule (filesystem-safe
names, Windows reserved names, duplicate handling, album/playlist layout) can
be unit-tested in isolation. The GTK application module executes the returned
plan and is the only place that actually touches the disk — keeping the risky
part small and the logic here pure, mirroring the isolated-helper pattern of
``core.metadata`` / ``core.quality`` / ``core.streamrip_status``.

The download pipeline itself is never touched: streamrip writes files exactly
as it always has (embedded tags, cover.jpg, track numbers in the name), and
organisation only relocates the finished files. Reorganisation is designed to
be safe:

  * Names are sanitised for both Linux and Windows (forbidden characters,
    reserved device names, trailing dots/spaces, length limits).
  * Empty / unknown values degrade to a stable fallback ("Unknown Artist",
    "Unknown Album", "Playlist - <service> - <id>") so a path is always valid.
  * Duplicate destination names are made unique with a numeric suffix instead
    of overwriting, so no file is ever silently clobbered.
"""

import posixpath
import re

# Characters Windows forbids in a path component. Backslash and forward slash
# are included too so a value that happens to contain a separator can never
# escape into a parent/child directory.
_WINDOWS_FORBIDDEN = '<>:"/\\|?*'
_FORBIDDEN_RE = re.compile('[' + re.escape(_WINDOWS_FORBIDDEN) + ']')

# C0 control characters are illegal on Windows and hostile on Linux.
_CONTROL_RE = re.compile(r'[\x00-\x1f\x7f]')

# Collapse runs of whitespace so sanitised names stay tidy.
_WS_RE = re.compile(r'\s+')

# Windows reserved device names (matched case-insensitively on the stem).
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

# Cap for a single path component. Kept well under the common 255-byte
# per-component limit to leave room for a dedupe suffix and an extension, and
# to stay safe on filesystems with tighter limits.
DEFAULT_MAX_COMPONENT = 150

# Inserted where a forbidden character is removed mid-name.
_REPLACEMENT = " "

# Fallbacks so a path component is never blank.
FALLBACK_ARTIST = "Unknown Artist"
FALLBACK_ALBUM = "Unknown Album"
FALLBACK_NAME = "Unknown"
PLAYLISTS_DIR = "Playlists"
PLAYLIST_FILE = "playlist.m3u"

# Audio extensions streamrip can produce (lower-case, with leading dot).
AUDIO_EXTENSIONS = frozenset({
    ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".oga",
    ".wav", ".aiff", ".aif", ".alac", ".wma",
})

# Human container label per extension for the <Quality> folder.
_CONTAINER_LABELS = {
    ".flac": "FLAC",
    ".mp3": "MP3",
    ".m4a": "AAC",
    ".aac": "AAC",
    ".ogg": "OGG",
    ".oga": "OGG",
    ".opus": "OPUS",
    ".wav": "WAV",
    ".aiff": "AIFF",
    ".aif": "AIFF",
    ".alac": "ALAC",
    ".wma": "WMA",
}


# ── Name sanitising ────────────────────────────────────────────────────────

def _split_ext(name):
    """Return ``(root, ext)`` where *ext* includes the dot, or ``("", "")``.

    Only treats a short, separator-free trailing segment as an extension so
    names like ``"Vol. 2"`` are not mistaken for a file extension.
    """
    dot = name.rfind(".")
    if dot <= 0:
        return name, ""
    ext = name[dot:]
    if 1 < len(ext) <= 11 and " " not in ext:
        return name[:dot], ext
    return name, ""


def _truncate(text, max_length, keep_extension):
    if keep_extension:
        root, ext = _split_ext(text)
        if ext:
            keep = max(1, max_length - len(ext))
            return root[:keep].strip(" .") + ext
    return text[:max_length]


def safe_filename(name, *, max_length=DEFAULT_MAX_COMPONENT,
                  fallback=FALLBACK_NAME, keep_extension=False):
    """Return *name* sanitised into a single filesystem-safe path component.

    Safe on both Linux and Windows:
      * removes path separators, the Windows-forbidden set ``<>:"/\\|?*`` and
        control characters,
      * collapses whitespace,
      * strips leading/trailing dots and spaces (Windows silently trims them,
        which would otherwise make a name not round-trip),
      * avoids the Windows reserved device names (CON, NUL, COM1 …),
      * truncates to *max_length* (preserving a file extension when
        *keep_extension* is set),
      * falls back to *fallback* when the result would be empty.

    Never returns ``""`` and never contains a path separator, so the result
    can always be joined safely into a path.
    """
    text = "" if name is None else str(name)
    text = _CONTROL_RE.sub("", text)
    text = _FORBIDDEN_RE.sub(_REPLACEMENT, text)
    text = _WS_RE.sub(" ", text).strip().strip(" .").strip()
    if not text:
        return fallback

    stem = text.split(".", 1)[0].strip().lower()
    if stem in _WINDOWS_RESERVED:
        text = "_" + text

    if max_length and len(text) > max_length:
        text = _truncate(text, max_length, keep_extension)

    text = text.strip(" .")
    return text or fallback


def album_artist_folder(artist, *, max_length=DEFAULT_MAX_COMPONENT):
    """Filesystem-safe folder name for an album artist.

    Stable for a given artist so albums downloaded separately land side by
    side under the same artist folder.
    """
    return safe_filename(artist, max_length=max_length, fallback=FALLBACK_ARTIST)


def album_folder(title, *, max_length=DEFAULT_MAX_COMPONENT):
    """Filesystem-safe folder name for an album title."""
    return safe_filename(title, max_length=max_length, fallback=FALLBACK_ALBUM)


def quality_folder(container, bit_depth=None, sampling_rate=None):
    """Folder name describing the audio quality, e.g. ``FLAC (16B-44100kHz)``.

    *container* is a human label (``"FLAC"``, ``"MP3"`` …). When both
    *bit_depth* and *sampling_rate* are known they are appended; otherwise the
    container alone is used (lossy formats have no meaningful bit depth).
    """
    label = safe_filename(container, fallback="Audio")
    if bit_depth and sampling_rate:
        return safe_filename(f"{label} ({bit_depth}B-{sampling_rate}kHz)",
                             fallback=label)
    return label


def playlist_folder(name, *, service=None, playlist_id=None,
                    max_length=DEFAULT_MAX_COMPONENT):
    """Filesystem-safe folder name for a playlist.

    Falls back to ``Playlist - <service> - <id>`` when the playlist name is
    unavailable, so the destination is always valid and identifiable.
    """
    safe = safe_filename(name, max_length=max_length, fallback="")
    if safe:
        return safe
    parts = ["Playlist"]
    if service:
        parts.append(str(service))
    if playlist_id:
        parts.append(str(playlist_id))
    fallback = " - ".join(parts)
    return safe_filename(fallback, max_length=max_length, fallback="Playlist")


# ── Duplicate handling ─────────────────────────────────────────────────────

def dedupe_filename(name, taken):
    """Return a version of *name* not present in *taken* (case-insensitively).

    *taken* is any iterable of names already in use. If *name* is free it is
    returned unchanged; otherwise a numeric suffix is inserted before the
    extension::

        track.flac -> track (2).flac -> track (3).flac ...

    Comparison is case-insensitive so the result is safe on case-insensitive
    filesystems (Windows, default macOS). The caller is responsible for adding
    the returned value to *taken* before the next call.
    """
    lowered = {str(t).lower() for t in taken}
    if name.lower() not in lowered:
        return name
    root, ext = _split_ext(name)
    n = 2
    while True:
        candidate = f"{root} ({n}){ext}"
        if candidate.lower() not in lowered:
            return candidate
        n += 1


# ── File-type helpers ──────────────────────────────────────────────────────

def is_audio_file(name):
    """True if *name* has a known audio extension."""
    _, ext = _split_ext(str(name))
    return ext.lower() in AUDIO_EXTENSIONS


def container_label(ext):
    """Human container label for a file extension (``.flac`` -> ``FLAC``)."""
    e = (ext or "").lower()
    if e and not e.startswith("."):
        e = "." + e
    return _CONTAINER_LABELS.get(e, e.lstrip(".").upper() or "Audio")


def dominant_container(filenames):
    """Most common audio container label among *filenames*, or ``""``.

    Used to label the <Quality> folder from the files actually written, so the
    label reflects reality even if the requested quality was downgraded.
    """
    counts = {}
    for name in filenames:
        if is_audio_file(name):
            _, ext = _split_ext(str(name))
            ext = ext.lower()
            counts[ext] = counts.get(ext, 0) + 1
    if not counts:
        return ""
    best = max(counts, key=lambda e: (counts[e], e))
    return container_label(best)


# ── m3u playlist body ──────────────────────────────────────────────────────

def m3u_content(entries):
    """Build a UTF-8 ``#EXTM3U`` playlist body from *entries*.

    *entries* is an ordered iterable of either a path string or a
    ``(path, title)`` / ``(path, title, seconds)`` tuple. Relative paths are
    recommended so the playlist stays portable when the folder is moved.
    """
    lines = ["#EXTM3U"]
    for entry in entries:
        if isinstance(entry, (tuple, list)):
            path = entry[0]
            title = entry[1] if len(entry) > 1 else ""
            seconds = entry[2] if len(entry) > 2 else -1
        else:
            path, title, seconds = entry, "", -1
        if title:
            try:
                secs = int(seconds)
            except (TypeError, ValueError):
                secs = -1
            lines.append(f"#EXTINF:{secs},{title}")
        lines.append(str(path))
    return "\n".join(lines) + "\n"


# ── Move planning (pure) ───────────────────────────────────────────────────

def _join(*parts):
    return posixpath.join(*[p for p in parts if p])


def plan_album_layout(filenames, *, album_artist, album_title, quality,
                      existing=None):
    """Plan where each album file should live under the library root.

    *filenames* are the basenames streamrip produced for the album (tracks,
    ``cover.jpg``, any sidecars). Returns a list of
    ``(source_filename, destination_relpath)`` pairs, where the destination is::

        <Album Artist>/<Album Title>/<Quality>/<filename>

    relative to the download root (POSIX separators). Files keep their
    streamrip-generated names — already ``"NN. Artist - Title.ext"`` and
    ``cover.jpg`` — so track numbers, cover art and embedded metadata are
    preserved untouched. Duplicate basenames (e.g. two discs each with a
    "01. …") are made unique with a numeric suffix. *existing* may list names
    already present in the destination so they are not overwritten.
    """
    base_dir = _join(album_artist_folder(album_artist),
                     album_folder(album_title),
                     safe_filename(quality, fallback="Audio"))
    return _plan_into(filenames, base_dir, existing)


def plan_playlist_layout(filenames, *, playlist_name, service=None,
                         playlist_id=None, parent=PLAYLISTS_DIR, existing=None):
    """Plan a playlist's flat layout under ``<parent>/<Playlist Name>/``.

    Returns a dict with:
      * ``folder``  — destination folder relpath under the library root,
      * ``moves``   — list of ``(source_filename, destination_relpath)``,
      * ``audio``   — destination basenames of audio tracks, in input order
                      (used to build ``playlist.m3u``).

    Input order is preserved so the playlist order is kept; the caller should
    pass *filenames* already ordered (e.g. by streamrip's numeric prefix).
    """
    folder = playlist_folder(playlist_name, service=service,
                             playlist_id=playlist_id)
    base_dir = _join(parent, folder) if parent else folder
    moves = _plan_into(filenames, base_dir, existing)
    audio = [posixpath.basename(dst) for _, dst in moves
             if is_audio_file(dst)]
    return {"folder": base_dir, "moves": moves, "audio": audio}


def _plan_into(filenames, base_dir, existing):
    taken = {str(e).lower() for e in (existing or [])}
    moves = []
    for name in filenames:
        dest_name = dedupe_filename(
            safe_filename(name, keep_extension=True), taken)
        taken.add(dest_name.lower())
        moves.append((name, _join(base_dir, dest_name)))
    return moves
