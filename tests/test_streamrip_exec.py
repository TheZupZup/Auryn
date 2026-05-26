"""Tests for the GTK-free streamrip executable resolver (``core.streamrip_exec``).

These guard the self-contained Windows packaging behaviour: a packaged build
must resolve the streamrip it ships internally, while Linux / run-from-source
must keep using the system ``rip`` exactly as before. The module is GTK-free
and fully injectable, so these run under plain ``pytest`` without a frozen
build, a display, or streamrip installed.
"""

from core import streamrip_exec as se


# ── packaged-build detection ────────────────────────────────────────────────

def test_is_frozen_injectable():
    assert se.is_frozen(frozen=True) is True
    assert se.is_frozen(frozen=False) is False


def test_is_windows_packaged_build_requires_frozen_and_windows():
    assert se.is_windows_packaged_build(frozen=True, system="Windows") is True
    assert se.is_windows_packaged_build(frozen=False, system="Windows") is False
    assert se.is_windows_packaged_build(frozen=True, system="Linux") is False
    assert se.is_windows_packaged_build(frozen=False, system="Linux") is False


def test_bundle_root_prefers_meipass():
    assert se.bundle_root(meipass="C:/app", executable="C:/app/Auryn.exe") == "C:/app"


def test_bundle_root_falls_back_to_executable_dir():
    root = se.bundle_root(meipass="", executable="/opt/auryn/Auryn")
    assert root == "/opt/auryn"


def test_streamrip_importable_uses_find_spec():
    assert se.streamrip_importable(find_spec=lambda name: object()) is True
    assert se.streamrip_importable(find_spec=lambda name: None) is False
    # A raising find_spec must be swallowed (treated as not importable).
    def boom(name):
        raise ImportError("nope")
    assert se.streamrip_importable(find_spec=boom) is False


# ── bundled streamrip resolution ────────────────────────────────────────────

def test_bundled_path_none_when_not_packaged():
    assert se.get_bundled_streamrip_path(frozen=False, system="Windows") is None
    assert se.get_bundled_streamrip_path(frozen=True, system="Linux") is None


def test_bundled_path_prefers_literal_executable():
    # A literal rip.exe shipped next to Auryn.exe wins over the multi-call form.
    cmd = se.get_bundled_streamrip_path(
        frozen=True, system="Windows",
        meipass="C:/app", executable="C:/app/Auryn.exe",
        isfile=lambda p: p == "C:/app/rip.exe",
        find_spec=lambda name: object(),
    )
    assert cmd == ["C:/app/rip.exe"]


def test_bundled_path_uses_multicall_when_streamrip_importable():
    cmd = se.get_bundled_streamrip_path(
        frozen=True, system="Windows",
        meipass="C:/app", executable="C:/app/Auryn.exe",
        isfile=lambda p: False,
        find_spec=lambda name: object(),
    )
    assert cmd == ["C:/app/Auryn.exe", se.RUN_STREAMRIP_FLAG]


def test_bundled_path_none_when_nothing_found():
    cmd = se.get_bundled_streamrip_path(
        frozen=True, system="Windows",
        meipass="C:/app", executable="C:/app/Auryn.exe",
        isfile=lambda p: False,
        find_spec=lambda name: None,
    )
    assert cmd is None


# ── configured path ─────────────────────────────────────────────────────────

def test_configured_path_returns_existing_file():
    assert se.get_configured_streamrip_path(
        "/custom/rip", isfile=lambda p: True) == ["/custom/rip"]


def test_configured_path_none_for_missing_or_empty():
    assert se.get_configured_streamrip_path("", isfile=lambda p: True) is None
    assert se.get_configured_streamrip_path(None, isfile=lambda p: True) is None
    assert se.get_configured_streamrip_path(
        "/missing/rip", isfile=lambda p: False) is None


# ── system PATH / common locations ──────────────────────────────────────────

def test_system_streamrip_prefers_which():
    cmd = se.find_system_streamrip(
        system="Linux", which=lambda name: "/usr/bin/rip")
    assert cmd == ["/usr/bin/rip"]


def test_system_streamrip_linux_common_locations():
    cmd = se.find_system_streamrip(
        system="Linux", which=lambda name: None,
        isfile=lambda p: p == "/usr/local/bin/rip")
    assert cmd == ["/usr/local/bin/rip"]


def test_system_streamrip_windows_appdata_scripts():
    env = {"APPDATA": "C:/Users/me/AppData/Roaming"}
    target = "C:/Users/me/AppData/Roaming/Python/Scripts/rip.exe"
    cmd = se.find_system_streamrip(
        system="Windows", which=lambda name: None, environ=env,
        isfile=lambda p: p == target, isdir=lambda p: False)
    assert cmd == [target]


def test_system_streamrip_none_when_absent():
    assert se.find_system_streamrip(
        system="Linux", which=lambda name: None,
        isfile=lambda p: False) is None


# ── full search order ───────────────────────────────────────────────────────

def test_search_order_bundled_beats_configured_and_system():
    cmd = se.get_streamrip_executable(
        configured_path="/custom/rip",
        frozen=True, system="Windows",
        meipass="C:/app", executable="C:/app/Auryn.exe",
        isfile=lambda p: True,            # both literal bundle + configured exist
        find_spec=lambda name: object(),
        which=lambda name: "/usr/bin/rip",
    )
    # Bundled literal rip.exe must win.
    assert cmd == ["C:/app/rip.exe"]


def test_search_order_configured_beats_system_when_not_packaged():
    cmd = se.get_streamrip_executable(
        configured_path="/custom/rip",
        frozen=False, system="Linux",
        isfile=lambda p: p == "/custom/rip",
        which=lambda name: "/usr/bin/rip",
    )
    assert cmd == ["/custom/rip"]


def test_search_order_falls_back_to_system():
    cmd = se.get_streamrip_executable(
        configured_path=None,
        frozen=False, system="Linux",
        isfile=lambda p: False,
        which=lambda name: "/usr/bin/rip",
    )
    assert cmd == ["/usr/bin/rip"]


def test_search_order_none_when_nothing_available():
    cmd = se.get_streamrip_executable(
        configured_path=None,
        frozen=False, system="Linux",
        isfile=lambda p: False,
        which=lambda name: None,
    )
    assert cmd is None


# ── command label ───────────────────────────────────────────────────────────

def test_describe_command():
    assert se.describe_streamrip_command(None) == "not found"
    assert se.describe_streamrip_command(["/usr/bin/rip"]) == "/usr/bin/rip"
    label = se.describe_streamrip_command(["C:/app/Auryn.exe", se.RUN_STREAMRIP_FLAG])
    assert "bundled streamrip" in label
    # The label must never be a misleading bare exe path for the multi-call form.
    assert "Auryn.exe" not in label


# ── multi-call dispatch ─────────────────────────────────────────────────────

def test_dispatch_returns_zero_on_clean_exit():
    def entry():
        raise SystemExit(0)
    assert se.dispatch_streamrip(["--version"], entry=entry,
                                 ensure_streams=False) == 0


def test_dispatch_returns_zero_when_entry_returns_normally():
    calls = {}
    def entry():
        calls["ran"] = True
    assert se.dispatch_streamrip(["url", "x"], entry=entry,
                                 ensure_streams=False) == 0
    assert calls["ran"] is True


def test_dispatch_propagates_nonzero_exit_code():
    def entry():
        raise SystemExit(2)
    assert se.dispatch_streamrip([], entry=entry, ensure_streams=False) == 2


def test_dispatch_maps_string_exit_to_one():
    def entry():
        raise SystemExit("some click error")
    assert se.dispatch_streamrip([], entry=entry, ensure_streams=False) == 1


def test_dispatch_sets_argv_for_streamrip():
    seen = {}
    def entry():
        import sys
        seen["argv"] = list(sys.argv)
    se.dispatch_streamrip(["url", "https://x"], entry=entry, ensure_streams=False)
    assert seen["argv"] == ["rip", "url", "https://x"]


def test_dispatch_reports_missing_entry_point(monkeypatch):
    # When streamrip's entry point cannot be resolved, dispatch reports a
    # distinct non-zero code without raising (independent of whether streamrip
    # happens to be installed in the test environment).
    monkeypatch.setattr(se, "_resolve_streamrip_entry", lambda: None)
    assert se.dispatch_streamrip(["--version"], ensure_streams=False) == 3
