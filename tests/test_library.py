"""Tests for the library-organisation helpers in ``core.library``.

These cover the pure, GTK-free layer that backs Auryn's post-download
reorganisation into a NAS / Jellyfin / Symfonium-friendly structure:
filesystem-safe names (Linux + Windows), album/playlist path generation,
duplicate filename handling and the multiple-albums-per-artist guarantee.
No file I/O happens here — only name/path computation is exercised.
"""

from core import library


# ── Safe filename generation ───────────────────────────────────────────────

def test_safe_filename_basic_passthrough():
    assert library.safe_filename("Daft Punk") == "Daft Punk"
    assert library.safe_filename("Discovery") == "Discovery"


def test_safe_filename_empty_uses_fallback():
    assert library.safe_filename("") == library.FALLBACK_NAME
    assert library.safe_filename(None) == library.FALLBACK_NAME
    assert library.safe_filename("   ") == library.FALLBACK_NAME
    assert library.safe_filename("", fallback="X") == "X"


def test_safe_filename_collapses_whitespace():
    assert library.safe_filename("A   B\t C") == "A B C"


def test_safe_filename_never_contains_separator():
    out = library.safe_filename("AC/DC")
    assert "/" not in out and "\\" not in out
    out2 = library.safe_filename("a\\b/c")
    assert "/" not in out2 and "\\" not in out2


# ── Windows-invalid characters and quirks ──────────────────────────────────

def test_windows_forbidden_characters_removed():
    # < > : " / \ | ? * are all illegal in a Windows path component.
    out = library.safe_filename('a<b>c:d"e/f\\g|h?i*j')
    for ch in '<>:"/\\|?*':
        assert ch not in out


def test_windows_trailing_dots_and_spaces_stripped():
    # Windows silently trims trailing dots/spaces; we must do so explicitly.
    assert library.safe_filename("name.") == "name"
    assert library.safe_filename("name ") == "name"
    assert library.safe_filename("name. . .") == "name"
    assert library.safe_filename("  spaced  ") == "spaced"


def test_windows_reserved_device_names_are_escaped():
    assert library.safe_filename("CON") != "CON"
    assert library.safe_filename("con").lower() != "con"
    assert library.safe_filename("NUL").endswith("NUL")
    assert library.safe_filename("COM1") != "COM1"
    # Reserved name with an extension is still reserved on Windows.
    assert library.safe_filename("con.flac") != "con.flac"
    # A normal name that merely contains a reserved substring is untouched.
    assert library.safe_filename("Control") == "Control"


def test_control_characters_removed():
    out = library.safe_filename("a\x00b\x1fc\x7fd")
    assert out == "abcd"


def test_long_names_truncated_gracefully():
    long = "x" * 500
    out = library.safe_filename(long)
    assert len(out) <= library.DEFAULT_MAX_COMPONENT
    assert out  # never empty


def test_long_filename_preserves_extension():
    long = "y" * 500 + ".flac"
    out = library.safe_filename(long, keep_extension=True)
    assert len(out) <= library.DEFAULT_MAX_COMPONENT
    assert out.endswith(".flac")


def test_dotted_album_title_not_treated_as_extension():
    # A short title with internal dots must survive intact (no truncation).
    assert library.safe_filename("Vol. 2") == "Vol. 2"
    assert library.safe_filename("M.A.C.H") == "M.A.C.H"


# ── Album path generation ──────────────────────────────────────────────────

def test_album_artist_and_album_folders():
    assert library.album_artist_folder("Avenged Sevenfold") == "Avenged Sevenfold"
    assert library.album_folder("Nightmare") == "Nightmare"


def test_album_folder_fallbacks():
    assert library.album_artist_folder("") == library.FALLBACK_ARTIST
    assert library.album_folder("") == library.FALLBACK_ALBUM


def test_quality_folder_with_and_without_specs():
    assert library.quality_folder("FLAC", 16, 44100) == "FLAC (16B-44100kHz)"
    assert library.quality_folder("FLAC", 24, 96000) == "FLAC (24B-96000kHz)"
    assert library.quality_folder("MP3") == "MP3"
    # Lossy formats: no bit depth even if a sample rate is somehow supplied.
    assert library.quality_folder("MP3", None, 44100) == "MP3"


def test_plan_album_layout_matches_desired_structure():
    files = ["01. Avenged Sevenfold - Nightmare.flac", "cover.jpg"]
    moves = library.plan_album_layout(
        files,
        album_artist="Avenged Sevenfold",
        album_title="Nightmare",
        quality="FLAC (16B-44100kHz)",
    )
    dests = dict(moves)
    assert dests["01. Avenged Sevenfold - Nightmare.flac"] == (
        "Avenged Sevenfold/Nightmare/FLAC (16B-44100kHz)/"
        "01. Avenged Sevenfold - Nightmare.flac"
    )
    # cover.jpg is preserved and relocated alongside the tracks.
    assert dests["cover.jpg"] == (
        "Avenged Sevenfold/Nightmare/FLAC (16B-44100kHz)/cover.jpg"
    )


def test_album_track_numbers_preserved_in_destination():
    files = [f"{n:02d}. Artist - Track {n}.flac" for n in range(1, 4)]
    moves = library.plan_album_layout(
        files, album_artist="Artist", album_title="Album",
        quality="FLAC (16B-44100kHz)")
    for src, dst in moves:
        assert dst.endswith(src)  # name (with NN. prefix) unchanged


# ── Multiple albums from the same artist sit side by side ──────────────────

def test_multiple_albums_same_artist_share_artist_folder():
    a = library.plan_album_layout(
        ["01. Avenged Sevenfold - Nightmare.flac"],
        album_artist="Avenged Sevenfold", album_title="Nightmare",
        quality="FLAC (16B-44100kHz)")
    b = library.plan_album_layout(
        ["01. Avenged Sevenfold - Shepherd of Fire.flac"],
        album_artist="Avenged Sevenfold", album_title="Hail to the King",
        quality="FLAC (16B-44100kHz)")
    artist_a = a[0][1].split("/")[0]
    artist_b = b[0][1].split("/")[0]
    assert artist_a == artist_b == "Avenged Sevenfold"
    # ...but the album folders differ, so they are siblings, not nested.
    assert a[0][1].split("/")[1] == "Nightmare"
    assert b[0][1].split("/")[1] == "Hail to the King"


# ── Duplicate filename handling ────────────────────────────────────────────

def test_dedupe_filename_first_use_unchanged():
    assert library.dedupe_filename("track.flac", set()) == "track.flac"


def test_dedupe_filename_appends_numeric_suffix():
    taken = {"track.flac"}
    out = library.dedupe_filename("track.flac", taken)
    assert out == "track (2).flac"
    taken.add(out.lower())
    assert library.dedupe_filename("track.flac", taken) == "track (3).flac"


def test_dedupe_filename_case_insensitive():
    assert library.dedupe_filename("Track.FLAC", {"track.flac"}) == "Track (2).FLAC"


def test_dedupe_filename_no_extension():
    assert library.dedupe_filename("cover", {"cover"}) == "cover (2)"


def test_plan_album_layout_dedupes_duplicate_basenames():
    # Two discs each contributing a "01." track must not collide.
    files = ["01. Artist - Intro.flac", "01. Artist - Intro.flac"]
    moves = library.plan_album_layout(
        files, album_artist="Artist", album_title="Album",
        quality="FLAC (16B-44100kHz)")
    dests = [d for _, d in moves]
    assert len(set(dests)) == len(dests)  # all unique


def test_plan_album_layout_respects_existing_names():
    moves = library.plan_album_layout(
        ["01. Artist - Song.flac"],
        album_artist="Artist", album_title="Album",
        quality="FLAC (16B-44100kHz)",
        existing=["01. Artist - Song.flac"])
    assert moves[0][1].endswith("01. Artist - Song (2).flac")


# ── Playlist path generation ───────────────────────────────────────────────

def test_playlist_folder_basic():
    assert library.playlist_folder("My Roadtrip Mix") == "My Roadtrip Mix"


def test_playlist_folder_fallback_when_name_missing():
    out = library.playlist_folder("", service="deezer", playlist_id="12345")
    assert out == "Playlist - deezer - 12345"
    # No service/id available still yields a valid, identifiable folder.
    assert library.playlist_folder(None) == "Playlist"


def test_plan_playlist_layout_uses_playlists_parent():
    files = ["01. A - One.flac", "02. B - Two.flac", "cover.jpg"]
    plan = library.plan_playlist_layout(files, playlist_name="Summer Hits")
    assert plan["folder"] == "Playlists/Summer Hits"
    for _, dst in plan["moves"]:
        assert dst.startswith("Playlists/Summer Hits/")


def test_plan_playlist_layout_preserves_order_and_lists_audio():
    files = ["01. A - One.flac", "02. B - Two.flac", "cover.jpg", "notes.txt"]
    plan = library.plan_playlist_layout(files, playlist_name="Mix")
    # Audio entries kept in input order; non-audio excluded from m3u list.
    assert plan["audio"] == ["01. A - One.flac", "02. B - Two.flac"]


def test_plan_playlist_layout_custom_parent():
    plan = library.plan_playlist_layout(
        ["01. A - One.flac"], playlist_name="Mix", parent="")
    assert plan["folder"] == "Mix"


def test_plan_playlist_dedupes_within_folder():
    files = ["01. A - One.flac", "01. A - One.flac"]
    plan = library.plan_playlist_layout(files, playlist_name="Mix")
    dests = [d for _, d in plan["moves"]]
    assert len(set(dests)) == 2


# ── Container / quality detection ──────────────────────────────────────────

def test_is_audio_file():
    assert library.is_audio_file("01. Artist - Song.flac")
    assert library.is_audio_file("song.MP3")
    assert not library.is_audio_file("cover.jpg")
    assert not library.is_audio_file("playlist.m3u")


def test_container_label():
    assert library.container_label(".flac") == "FLAC"
    assert library.container_label("mp3") == "MP3"
    assert library.container_label(".m4a") == "AAC"
    assert library.container_label(".weird") == "WEIRD"


def test_dominant_container():
    assert library.dominant_container(
        ["a.flac", "b.flac", "cover.jpg"]) == "FLAC"
    assert library.dominant_container(["a.mp3", "b.mp3"]) == "MP3"
    assert library.dominant_container(["cover.jpg"]) == ""


# ── m3u body ───────────────────────────────────────────────────────────────

def test_m3u_content_plain_paths():
    body = library.m3u_content(["01. A - One.flac", "02. B - Two.flac"])
    assert body.startswith("#EXTM3U\n")
    assert "01. A - One.flac" in body
    assert "02. B - Two.flac" in body
    assert body.endswith("\n")


def test_m3u_content_with_extinf():
    body = library.m3u_content([("01. A - One.flac", "A - One", 215)])
    assert "#EXTINF:215,A - One" in body
    assert "01. A - One.flac" in body
