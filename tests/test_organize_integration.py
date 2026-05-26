"""Integration tests for post-download library organisation.

These drive the *real* ``AurynApp`` organisation methods against temporary
directories laid out exactly as streamrip leaves them, so the behaviour the
PR test-plan describes is verified end to end (minus the network download and
GTK rendering, which cannot run headlessly). The streamrip download itself is
never invoked — we only feed in the files it would have produced and check
that they are relocated into the expected library tree.

The GTK application module imports cleanly without a display because GTK is
imported lazily (see ``Auryn._import_gtk``); if that ever changes these tests
skip rather than fail the suite.
"""

import inspect
import os
import types

import pytest

try:
    import Auryn
except Exception as exc:  # pragma: no cover - defensive: never break the suite
    pytest.skip(f"Auryn module unavailable: {exc}", allow_module_level=True)

from core import metadata

App = Auryn.AurynApp

# Methods copied onto the fake ``self`` so the real implementations run.
_ORG_METHODS = (
    "_organize_download", "_organize_album", "_organize_playlist",
    "_quality_folder_label", "_collect_files", "_sort_playlist_files",
    "_playlist_name", "_playlist_id", "_execute_moves",
    "_write_playlist_m3u", "_cleanup_empty_dirs", "_remember_album_meta",
)


def _app(base, *, is_playlist=False, album_meta=None,
         url="https://www.deezer.com/en/album/123", quality="2",
         organize=True, playlists_subfolder=True):
    """A GTK-free stand-in carrying the real organisation methods."""
    s = types.SimpleNamespace()
    s.logs = []
    s._log = lambda text="", tag=None: s.logs.append(text)
    s._config = {"organize_library": organize,
                 "playlists_subfolder": playlists_subfolder}
    s._dest_folder = base
    s._active_url = url
    s._active_quality = quality
    s._active_is_playlist = is_playlist
    s._album_meta = album_meta
    s._FLAC_QUALITY_SPECS = App._FLAC_QUALITY_SPECS
    for name in _ORG_METHODS:
        raw = inspect.getattr_static(App, name)
        if isinstance(raw, staticmethod):
            setattr(s, name, getattr(App, name))
        else:
            setattr(s, name, getattr(App, name).__get__(s, App))
    return s


def _tree(base):
    out = []
    for root, _dirs, files in os.walk(base):
        for f in files:
            out.append(os.path.relpath(os.path.join(root, f), base).replace(os.sep, "/"))
    return sorted(out)


def _touch(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)


# ── Test-plan item 1: Deezer album layout ──────────────────────────────────

def test_plan1_deezer_album_layout(tmp_path):
    base = str(tmp_path)
    src = os.path.join(base, "Avenged Sevenfold - Nightmare (2010) [FLAC]")
    _touch(os.path.join(src, "01. Avenged Sevenfold - Nightmare.flac"))
    _touch(os.path.join(src, "02. Avenged Sevenfold - So Far Away.flac"))
    _touch(os.path.join(src, "cover.jpg"))

    s = _app(base, album_meta={"artist": "Avenged Sevenfold",
                               "album": "Nightmare"})
    result = s._organize_download(src)

    t = _tree(base)
    qdir = "Avenged Sevenfold/Nightmare/FLAC (16B-44100kHz)"
    assert f"{qdir}/01. Avenged Sevenfold - Nightmare.flac" in t
    assert f"{qdir}/02. Avenged Sevenfold - So Far Away.flac" in t
    assert f"{qdir}/cover.jpg" in t            # cover preserved
    assert not os.path.exists(src)             # streamrip folder cleaned up
    assert result == os.path.join(base, "Avenged Sevenfold", "Nightmare")


# ── Test-plan item 2: multiple albums, same artist, side by side ───────────

def test_plan2_multiple_albums_same_artist(tmp_path):
    base = str(tmp_path)

    a = os.path.join(base, "AVS - Nightmare [FLAC]")
    _touch(os.path.join(a, "01. Avenged Sevenfold - Nightmare.flac"))
    _app(base, album_meta={"artist": "Avenged Sevenfold",
                           "album": "Nightmare"})._organize_download(a)

    b = os.path.join(base, "AVS - Hail to the King [FLAC]")
    _touch(os.path.join(b, "01. Avenged Sevenfold - Shepherd of Fire.flac"))
    _app(base, album_meta={"artist": "Avenged Sevenfold",
                           "album": "Hail to the King"})._organize_download(b)

    t = _tree(base)
    assert any(p.startswith("Avenged Sevenfold/Nightmare/") for p in t)
    assert any(p.startswith("Avenged Sevenfold/Hail to the King/") for p in t)
    # Exactly one artist folder at the top level (the two albums are siblings).
    top = {p.split("/")[0] for p in t}
    assert top == {"Avenged Sevenfold"}


# ── Test-plan item 3: playlist layout, m3u and order ───────────────────────

def test_plan3_playlist_layout_and_m3u(tmp_path):
    base = str(tmp_path)
    src = os.path.join(base, "My Roadtrip Mix")
    # Deliberately created out of order; organisation must sort by track no.
    _touch(os.path.join(src, "02. B Band - Second.flac"))
    _touch(os.path.join(src, "01. A Band - First.flac"))
    _touch(os.path.join(src, "03. C Band - Third.flac"))
    _touch(os.path.join(src, "cover.jpg"))

    s = _app(base, is_playlist=True,
             url="https://www.deezer.com/en/playlist/789")
    result = s._organize_download(src)

    t = _tree(base)
    pdir = "Playlists/My Roadtrip Mix"
    assert f"{pdir}/01. A Band - First.flac" in t
    assert f"{pdir}/02. B Band - Second.flac" in t
    assert f"{pdir}/03. C Band - Third.flac" in t
    assert f"{pdir}/cover.jpg" in t             # cover preserved
    assert f"{pdir}/playlist.m3u" in t          # m3u generated
    assert result == os.path.join(base, "Playlists", "My Roadtrip Mix")

    with open(os.path.join(base, pdir, "playlist.m3u")) as fh:
        m3u = fh.read()
    assert m3u.startswith("#EXTM3U")
    # Order preserved, cover excluded from the playlist body.
    assert m3u.index("01. A Band - First.flac") < m3u.index("02. B Band - Second.flac")
    assert m3u.index("02. B Band - Second.flac") < m3u.index("03. C Band - Third.flac")
    assert "cover.jpg" not in m3u


def test_plan3_playlist_name_fallback(tmp_path):
    base = str(tmp_path)
    # streamrip could not name the folder after the playlist.
    src = os.path.join(base, "")  # not usable; emulate via a blank-ish name
    src = os.path.join(base, " ")
    _touch(os.path.join(src, "01. A - One.flac"))
    s = _app(base, is_playlist=True,
             url="https://www.deezer.com/en/playlist/55555")
    result = s._organize_download(src)
    # Falls back to "Playlist - <service> - <id>".
    assert os.path.basename(result) == "Playlist - deezer - 55555"


# ── Test-plan item 4: settings toggles ─────────────────────────────────────

def test_plan4_organize_disabled_leaves_files(tmp_path):
    base = str(tmp_path)
    src = os.path.join(base, "Artist - Album [FLAC]")
    _touch(os.path.join(src, "01. Artist - Song.flac"))
    s = _app(base, album_meta={"artist": "Artist", "album": "Album"},
             organize=False)
    result = s._organize_download(src)
    assert "Artist - Album [FLAC]/01. Artist - Song.flac" in _tree(base)
    assert result == src


def test_plan4_playlists_subfolder_disabled_stays_flat(tmp_path):
    base = str(tmp_path)
    src = os.path.join(base, "Flat Mix")
    _touch(os.path.join(src, "01. A - One.flac"))
    s = _app(base, is_playlist=True, playlists_subfolder=False,
             url="https://www.deezer.com/en/playlist/1")
    s._organize_download(src)
    t = _tree(base)
    assert "Flat Mix/01. A - One.flac" in t
    assert not any(p.startswith("Playlists/") for p in t)


# ── Test-plan item 5: Qobuz path + metadata sidebar unaffected ─────────────

def test_plan5_qobuz_hires_album_layout(tmp_path):
    base = str(tmp_path)
    src = os.path.join(base, "Air - Moon Safari [FLAC]")
    _touch(os.path.join(src, "01. Air - La Femme d'Argent.flac"))
    _touch(os.path.join(src, "cover.jpg"))
    s = _app(base, album_meta={"artist": "Air", "album": "Moon Safari"},
             url="https://open.qobuz.com/album/abc123", quality="3")
    s._organize_download(src)
    t = _tree(base)
    # Qobuz hi-res FLAC (quality 3) -> 24-bit / 96 kHz quality folder.
    assert "Air/Moon Safari/FLAC (24B-96000kHz)/01. Air - La Femme d'Argent.flac" in t
    assert "Air/Moon Safari/FLAC (24B-96000kHz)/cover.jpg" in t


def test_plan5_metadata_sidebar_parsing_unaffected(tmp_path):
    # The sidebar parsing layer (core.metadata) is unchanged: it still yields
    # the expected fields, and the new _remember_album_meta only *reads* them.
    deezer_fields = metadata.deezer_album_fields(
        {"artist": {"name": "Daft Punk"}, "title": "Discovery"})
    qobuz_fields = metadata.qobuz_album_fields(
        {"artist": {"name": "Air"}, "title": "Moon Safari"})
    assert deezer_fields["artist"] == "Daft Punk"
    assert qobuz_fields["album"] == "Moon Safari"

    s = _app(str(tmp_path))
    before = dict(qobuz_fields)
    s._remember_album_meta(qobuz_fields)
    assert s._album_meta == {"artist": "Air", "album": "Moon Safari"}
    assert qobuz_fields == before  # input payload not mutated


def test_plan5_remember_album_meta_tolerates_bad_payload(tmp_path):
    s = _app(str(tmp_path))
    for bad in (None, [], "oops", 42, {}):
        s._album_meta = None
        s._remember_album_meta(bad)  # must not raise
        assert s._album_meta is None


# ── Safety: failure leaves files in place with the required warning ────────

def test_failure_leaves_files_and_warns(tmp_path, monkeypatch):
    base = str(tmp_path)
    src = os.path.join(base, "Artist - Album [FLAC]")
    _touch(os.path.join(src, "01. Artist - Song.flac"))
    s = _app(base, album_meta={"artist": "Artist", "album": "Album"})

    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(Auryn.shutil, "move", boom)

    result = s._organize_download(src)
    assert result == src
    assert os.path.exists(os.path.join(src, "01. Artist - Song.flac"))
    assert any("library organization failed" in str(m) for m in s.logs)


def test_redownload_same_content_is_idempotent(tmp_path):
    base = str(tmp_path)
    src = os.path.join(base, "Artist - Album [FLAC]")
    _touch(os.path.join(src, "01. Artist - Song.flac"))
    s = _app(base, album_meta={"artist": "Artist", "album": "Album"})
    first = s._organize_download(src)
    tree1 = _tree(base)
    # Re-run organisation pointing at the already-organised folder.
    s._organize_download(first)
    assert _tree(base) == tree1
    assert sum(1 for p in _tree(base) if p.endswith(".flac")) == 1
