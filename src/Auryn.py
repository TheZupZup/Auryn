#!/usr/bin/env python3
"""
Auryn v0.1.1 — GUI wrapper for streamrip
© 2025 TheZupZup — GNU GPL v3
UI chargée depuis Auryn.ui (Glade)
"""


import os
import re
import threading
import subprocess
import urllib.request
import json
import tempfile
import platform
import shutil
import sys
import io
import time
import contextlib
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.errors import parse_streamrip_error
from core.status import build_status_markup
from core import tidal_auth
from core import metadata
from core import streamrip_status
from core import log_format
from core import deezer
from core import library
from core import quality as qual
from core import streamrip_exec

APP_NAME = "Auryn"
APP_VERSION = "0.1.1"

SYSTEM_NAME = platform.system()
IS_WINDOWS = SYSTEM_NAME == "Windows"
IS_MACOS = SYSTEM_NAME == "Darwin"
IS_UNSUPPORTED_OS = IS_WINDOWS or IS_MACOS

pty = None
fcntl = None

if not IS_WINDOWS:
    import pty
    import fcntl


def _import_gtk():
    """Import GTK into module globals; deferred so CLI flags work without GTK."""
    global Gtk, GLib, Gdk, GdkPixbuf, Pango
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, GLib, Gdk, GdkPixbuf, Pango


CSS = b"""
* { font-family: 'Ubuntu', 'Cantarell', sans-serif; }
window { background-color: #1a1a1a; color: #e8e8e8; }
#header_bar { background-color: #0f0f0f; border-bottom: 2px solid #FF6B35; padding: 8px 14px; min-height: 48px; }
#right_panel { background-color: #111111; border-left: 1px solid #252525; padding: 10px; min-width: 200px; }
#url_entry { background-color: #0d0d0d; color: #e8e8e8; border: 1px solid #333; border-radius: 4px; padding: 7px 11px; font-family: 'Ubuntu Mono', monospace; font-size: 12px; caret-color: #FF6B35; transition: border-color 120ms ease; }
#url_entry:focus { border-color: #FF6B35; }
.cred-entry { background-color: #0d0d0d; color: #e8e8e8; border: 1px solid #333; border-radius: 3px; padding: 6px 10px; font-family: 'Ubuntu Mono', monospace; font-size: 12px; caret-color: #FF6B35; }
.cred-entry:focus { border-color: #FF6B35; }
#quality_box { background-color: #111111; border: 1px solid #252525; border-radius: 3px; padding: 5px 12px; }
checkbutton { color: #aaaaaa; font-size: 12px; }
checkbutton check { background-color: #0d0d0d; border-color: #444; border-radius: 2px; min-width: 14px; min-height: 14px; }
checkbutton:checked check { background-color: #FF6B35; border-color: #FF6B35; }
checkbutton label:hover { color: #FF6B35; }
.neutral-btn { background-color: #252525; color: #aaaaaa; border: 1px solid #333; border-radius: 4px; padding: 5px 12px; font-size: 11px; transition: all 120ms ease; }
.neutral-btn:hover { background-color: #2e2e2e; color: #ffffff; border-color: #FF6B35; }
#btn_download { background-color: #FF6B35; color: #ffffff; border: none; border-radius: 4px; padding: 7px 18px; font-size: 13px; font-weight: bold; transition: background-color 120ms ease; }
#btn_download:hover { background-color: #ff7d4d; }
#btn_download:disabled { background-color: #333; color: #666; }
#btn_stop { background-color: #c0392b; color: #ffffff; border: none; border-radius: 4px; padding: 7px 16px; font-size: 13px; font-weight: bold; transition: background-color 120ms ease; }
#btn_stop:hover { background-color: #e74c3c; }
#log_view { background-color: #080808; color: #bbbbbb; font-family: 'Ubuntu Mono', 'Courier New', monospace; font-size: 11px; padding: 8px; }
#log_scroll { border: 1px solid #252525; border-radius: 3px; }
#lyrics_label { font-family: 'Ubuntu', sans-serif; padding: 4px; }
notebook { background-color: #0d0d0d; border: 1px solid #252525; border-radius: 3px; }
notebook stack { background-color: #0d0d0d; padding: 10px; }
notebook tab { background-color: #111111; color: #888; border: none; padding: 5px 14px; transition: color 120ms ease; }
notebook tab:hover { color: #cccccc; }
notebook tab:checked { background-color: #FF6B35; color: #ffffff; font-weight: bold; }
progressbar trough { background-color: #0d0d0d; border: 1px solid #252525; border-radius: 3px; min-height: 4px; }
progressbar progress { background-color: #FF6B35; border-radius: 3px; min-height: 4px; }
#footer_bar { background-color: #0a0a0a; border-top: 1px solid #222; padding: 3px 12px; min-height: 22px; }
separator { background-color: #252525; }
.history-row { background-color: #0d0d0d; border: 1px solid #1f1f1f; border-radius: 3px; }
.history-row:hover { border-color: #333; }
"""

# Sourced from core.quality so the picker, the clamping rules and the log
# messages share one definition (the GTK widget labels live in Auryn.ui and
# match these exactly).
QUALITY_LABELS = qual.QUALITY_LABELS
QUALITY_VALUES = qual.QUALITY_VALUES

# streamrip authenticates the TIDAL client (device/web login) before it ever
# resolves or downloads a URL, so any syntactically valid TIDAL link is enough
# to trigger the login flow. The assisted setup terminates streamrip as soon
# as the tokens are written, so this URL is never actually downloaded.
TIDAL_LOGIN_PROBE_URL = "https://tidal.com/browse/album/1"

# Matches the device/web login link streamrip prints (link.tidal.com / a
# login.tidal.com authorize URL). Token blobs never match this.
TIDAL_LOGIN_URL_RE = re.compile(r'https?://[^\s\'"<>]*tidal[^\s\'"<>]*', re.I)


def detect_service_and_id(url):
    url = url.strip()
    m = re.search(r'qobuz\.com/[^/]+/album/[^/]+/([a-z0-9]+)/?', url, re.I)
    if m: return ("qobuz", m.group(1))
    m = re.search(r'(?:open\.)?qobuz\.com/albu[mn]/([a-z0-9]+)/?', url, re.I)
    if m: return ("qobuz", m.group(1))
    m = re.search(r'deezer\.com/(?:[^/]+/)?album/(\d+)', url)
    if m: return ("deezer", m.group(1))
    m = re.search(r'deezer\.com/(?:[^/]+/)?track/(\d+)', url)
    if m: return ("deezer_track", m.group(1))
    m = re.search(r'tidal\.com/(?:browse/)?album/(\d+)', url)
    if m: return ("tidal", m.group(1))
    if "soundcloud.com" in url: return ("soundcloud", None)
    return (None, None)


def url_is_playlist(url):
    """Best-effort: True if *url* points at a playlist rather than an album.

    Used only to route post-download organisation (playlists go under a
    dedicated folder). SoundCloud calls them "sets". Conservative: anything
    not clearly a playlist is treated as an album/track.
    """
    return bool(re.search(r'/(?:playlist|sets)/', url or "", re.I))


def fetch_qobuz_meta(album_id):
    urls_to_try = [
        f"https://www.qobuz.com/api.json/0.2/album/get?album_id={album_id}&limit=50",
    ]
    for api_url in urls_to_try:
        try:
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "Mozilla/5.0", "X-App-Id": "950096963"}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode())
        except Exception:
            pass
    return None


def fetch_json(url_str):
    try:
        req = urllib.request.Request(url_str, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def fetch_deezer_album(album_id):
    return fetch_json(f"https://api.deezer.com/album/{album_id}")


def fetch_deezer_track_album(track_id):
    data = fetch_json(f"https://api.deezer.com/track/{track_id}")
    if data and "album" in data:
        return fetch_deezer_album(data["album"]["id"])
    return None


def download_cover(cover_url, size=185):
    try:
        req = urllib.request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read()
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
        pb = loader.get_pixbuf()
        if pb:
            return pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
    except Exception:
        pass
    return None


def resolve_config_dir():
    """Locate streamrip's config directory the same way streamrip does.

    streamrip uses click.get_app_dir("streamrip"): on Windows that is
    %APPDATA%\\streamrip, and on Linux it is $XDG_CONFIG_HOME/streamrip
    (defaulting to ~/.config/streamrip).
    """
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "streamrip")
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg, "streamrip")


def toml_escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def resolve_auryn_data_dir():
    if IS_WINDOWS:
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "Auryn")
    return os.path.expanduser("~/.config/Auryn")


def auryn_config_path():
    return os.path.join(resolve_auryn_data_dir(), "config.json")


def is_first_launch():
    """Return True when no Auryn config file exists yet on disk."""
    return not os.path.exists(auryn_config_path())


DEFAULT_CONFIG = {
    "download_folder": os.path.expanduser("~/Music"),
    "quality_level": 3,
    # Organise finished downloads into a tidy NAS / Jellyfin / Symfonium
    # library tree (<Album Artist>/<Album>/<Quality>/…). Post-processing only;
    # the streamrip download pipeline is untouched, and on any failure the
    # original files are left exactly where streamrip wrote them.
    "organize_library": True,
    # Group playlists under a dedicated "Playlists" folder.
    "playlists_subfolder": True,
}


def load_config():
    """Read user preferences from config.json, returning defaults if missing or corrupt."""
    path = auryn_config_path()
    if not os.path.exists(path):
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    if isinstance(data, dict):
        merged.update(data)
    return merged


def save_config(data):
    """Persist user preferences to config.json, creating the directory if needed."""
    path = auryn_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def resolve_log_dir():
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base, "Auryn", "logs")
    return os.path.expanduser("~/.local/state/Auryn")


def open_in_file_manager(path):
    if IS_WINDOWS:
        os.startfile(path)
    elif IS_MACOS:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def run_doctor(verbose=False):
    """Fail-fast environment check; prints only the first problem found.

    On a packaged Windows build it additionally reports the packaged status,
    whether the bundled streamrip was found, the streamrip config path and
    whether Deezer is configured — all without ever exposing the ARL.
    """
    rip_search_paths = [
        os.path.expanduser("~/.local/bin/rip"),
        "/usr/local/bin/rip",
        "/usr/bin/rip",
    ]
    cfg_path = os.path.join(resolve_config_dir(), "config.toml")
    folder = os.path.expanduser("~/Music")
    packaged = streamrip_exec.is_windows_packaged_build()
    configured_rip = (os.environ.get("AURYN_STREAMRIP")
                      or os.environ.get("AURYN_RIP"))
    rip_cmd = streamrip_exec.get_streamrip_executable(
        configured_path=configured_rip)

    if verbose:
        print(f"INFO  Python version: {sys.version.split()[0]}")
        print(f"INFO  Python executable: {sys.executable}")
        print(f"INFO  Platform: {platform.platform()}")
        print(f"INFO  streamrip config path: {cfg_path}")
        print(f"INFO  Default download folder: {folder}")
        try:
            print(tidal_auth.auth_debug_report(cfg_path))
        except Exception as exc:
            print(f"INFO  TIDAL auth report unavailable: {exc}")

    # Packaged Windows report (always shown, not just in verbose mode).
    if packaged:
        print("INFO  Auryn packaged mode detected (self-contained Windows build).")
        bundled = streamrip_exec.get_bundled_streamrip_path()
        if bundled:
            print(f"OK    Bundled streamrip found: {streamrip_exec.describe_streamrip_command(bundled)}")
        else:
            print("FAIL  Bundled streamrip NOT found inside the package.")
        print(f"INFO  streamrip config path: {cfg_path}")
        try:
            arl_present = bool(deezer.deezer_config_status(cfg_path).get("arl_present"))
        except Exception:
            arl_present = False
        print(f"INFO  Deezer configured: {'yes' if arl_present else 'no'}")

    if sys.version_info < (3, 8):
        print(f"FAIL  Python >= 3.8 required (found {sys.version.split()[0]})")
        return False

    try:
        import gi as _gi
        _gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk as _Gtk  # noqa: F401
    except Exception as exc:
        print(f"FAIL  GTK/PyGObject unavailable: {exc}")
        return False

    if not rip_cmd:
        if packaged:
            print("FAIL  Bundled streamrip not found inside the Auryn package.")
        else:
            print("FAIL  streamrip (rip) not found in PATH or common locations.")
            if verbose:
                print("INFO  Paths searched for rip:")
                print("        $PATH (via shutil.which)")
                for _c in rip_search_paths:
                    print(f"        {_c}")
        return False
    if verbose:
        print(f"INFO  streamrip command: {streamrip_exec.describe_streamrip_command(rip_cmd)}")

    if not os.path.exists(cfg_path):
        print(f"FAIL  streamrip config not found: {cfg_path}  (run: rip config reset)")
        return False

    try:
        os.makedirs(folder, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, delete=True):
            pass
    except Exception:
        print(f"FAIL  Default download folder not writable: {folder}")
        return False

    print("OK  All checks passed.")
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  AurynApp — charge l'UI depuis Auryn.ui
# ─────────────────────────────────────────────────────────────────────────────

class AurynApp:

    def __init__(self):
        # ── CSS ──
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)

        # ── Charger le fichier .ui ──
        ui_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Auryn.ui")
        if not os.path.exists(ui_file):
            # Fallback: même dossier que le script
            ui_file = os.path.join(os.path.dirname(__file__), "Auryn.ui")

        self.builder = Gtk.Builder()
        self.builder.add_from_file(ui_file)

        # ── Récupérer tous les widgets depuis le .ui ──
        self.window        = self.builder.get_object("main_window")
        self.url_entry     = self.builder.get_object("url_entry")
        self.btn_download  = self.builder.get_object("btn_download")
        self.btn_stop      = self.builder.get_object("btn_stop")
        self.btn_about     = self.builder.get_object("btn_about")
        self.btn_setup       = self.builder.get_object("btn_setup")
        self.btn_credentials = self.builder.get_object("btn_credentials")
        self.btn_diagnostics = self.builder.get_object("btn_diagnostics")
        self.btn_choose    = self.builder.get_object("btn_choose_folder")
        self.btn_open      = self.builder.get_object("btn_open_folder")
        self.btn_open_downloads = self.builder.get_object("btn_open_downloads_folder")
        self.btn_log       = self.builder.get_object("btn_open_log")
        self.btn_copy_log  = self.builder.get_object("btn_copy_log")
        self.cb_clear_cache = self.builder.get_object("cb_clear_cache")
        self.cb_organize    = self.builder.get_object("cb_organize_library")
        self.cb_playlists_subfolder = self.builder.get_object("cb_playlists_subfolder")
        self.folder_lbl    = self.builder.get_object("folder_lbl")
        self.status_lbl    = self.builder.get_object("status_lbl")
        self.progress_bar  = self.builder.get_object("progress_bar")
        self.log_view      = self.builder.get_object("log_view")
        self.cover_img     = self.builder.get_object("cover_img")
        self.cover_lbl     = self.builder.get_object("cover_lbl")
        self.footer_lbl    = self.builder.get_object("footer_lbl")
        self.speed_lbl     = self.builder.get_object("speed_lbl")
        self._scroll       = self.builder.get_object("log_scroll")
        self.notebook      = self.builder.get_object("notebook")
        self.lyrics_label  = self.builder.get_object("lyrics_label")
        self.history_listbox     = self.builder.get_object("history_listbox")
        self.history_empty_label = self.builder.get_object("history_empty_label")
        self.btn_add_queue       = self.builder.get_object("btn_add_queue")
        self.btn_clear_queue     = self.builder.get_object("btn_clear_queue")
        self.queue_listbox       = self.builder.get_object("queue_listbox")
        self.queue_empty_label   = self.builder.get_object("queue_empty_label")

        # ── Checkbuttons qualité ──
        self._quality_checks = [
            self.builder.get_object("cb_mp3_128"),
            self.builder.get_object("cb_mp3_320"),
            self.builder.get_object("cb_flac_16"),
            self.builder.get_object("cb_flac_24"),
            self.builder.get_object("cb_max"),
        ]

        # ── Labels métadonnées (correspondent aux IDs dans le .ui) ──
        self._meta = {
            "Album Artist": self.builder.get_object("meta_artist"),
            "Album":        self.builder.get_object("meta_album"),
            "Album Quality":self.builder.get_object("meta_quality"),
            "Total Tracks": self.builder.get_object("meta_tracks"),
            "UPC":          self.builder.get_object("meta_upc"),
            "Release Date": self.builder.get_object("meta_date"),
        }

        # ── État interne ──
        self._config           = load_config()
        self._process          = None
        self._dest_folder      = self._config.get("download_folder", os.path.expanduser("~/Music"))
        self._track_done       = 0
        self._total_tracks     = 0
        self._last_known_error = None
        self._download_history     = []
        self._current_history_entry = None
        self._dest_dirs_snapshot   = set()
        self._queue                 = []
        self._current_queue_item    = None
        self._queue_seq             = 0
        self._queue_stopped_by_user = False
        self._active_url            = None
        self._tidal_auth_required   = False
        self._tidal_auth_corrupted  = False
        self._tb_noise_notified     = False
        self._dl_error_count        = 0
        self._dl_skip_count         = 0
        self._dl_invalid_url        = False
        self._dl_finished_marker    = False
        self._cfg_fingerprint_pre   = None
        # Context captured per-download for post-download library organisation.
        self._album_meta            = None
        self._active_is_playlist    = False
        self._active_quality        = None

        # ── Forcer can-focus sur les widgets interactifs ──
        self.url_entry.set_can_focus(True)
        self.btn_download.set_can_focus(True)
        self.btn_stop.set_can_focus(True)
        self.btn_choose.set_can_focus(True)
        self.btn_open.set_can_focus(True)
        self.btn_open_downloads.set_can_focus(True)
        self.btn_log.set_can_focus(True)
        if self.btn_copy_log is not None:
            self.btn_copy_log.set_can_focus(True)
        self.btn_about.set_can_focus(True)
        self.btn_setup.set_can_focus(True)
        self.btn_credentials.set_can_focus(True)
        self.btn_diagnostics.set_can_focus(True)
        self.btn_add_queue.set_can_focus(True)
        self.btn_clear_queue.set_can_focus(True)
        self.cb_clear_cache.set_can_focus(True)
        if self.cb_organize is not None:
            self.cb_organize.set_can_focus(True)
        if self.cb_playlists_subfolder is not None:
            self.cb_playlists_subfolder.set_can_focus(True)
        for cb in self._quality_checks:
            cb.set_can_focus(True)

        # ── Tags de couleur dans le log ──
        buf = self.log_view.get_buffer()
        buf.create_tag("ok",    foreground="#87a556")
        buf.create_tag("error", foreground="#e74c3c")
        buf.create_tag("track", foreground="#FF6B35")
        buf.create_tag("info",  foreground="#555555")
        buf.create_tag("dim",   foreground="#333333")

        # ── Pochette placeholder ──
        self._set_placeholder_cover()

        # ── Connecter les signaux ──
        self.window.connect("destroy", self._on_quit)
        self.url_entry.connect("activate", self._on_download)
        self.btn_download.connect("clicked", self._on_download)
        self.btn_stop.connect("clicked", self._on_stop)
        self.btn_about.connect("clicked", self._show_about)
        self.btn_setup.connect("clicked", self._show_setup_wizard)
        self.btn_credentials.connect("clicked", self._show_credentials_dialog)
        self.btn_diagnostics.connect("clicked", self._show_diagnostics)
        self.btn_choose.connect("clicked", self._choose_folder)
        self.btn_open.connect("clicked", self._open_folder)
        self.btn_open_downloads.connect("clicked", self._open_downloads_folder)
        self.btn_log.connect("clicked", self._open_log_folder)
        if self.btn_copy_log is not None:
            self.btn_copy_log.connect("clicked", self._copy_log_to_clipboard)
        self.btn_add_queue.connect("clicked", self._on_add_to_queue)
        self.btn_clear_queue.connect("clicked", self._on_clear_queue)

        for i, cb in enumerate(self._quality_checks):
            cb.connect("toggled", self._on_quality_toggled, i)

        if self.cb_organize is not None:
            self.cb_organize.connect("toggled", self._on_organize_toggled)
        if self.cb_playlists_subfolder is not None:
            self.cb_playlists_subfolder.connect("toggled",
                                                self._on_organize_toggled)

        # ── Restaurer les préférences enregistrées ──
        self._apply_saved_preferences()

        # ── Afficher ──
        self.window.show_all()
        self.btn_stop.hide()
        self._is_first_launch = is_first_launch()
        if self._is_first_launch:
            GLib.idle_add(self._show_first_launch_welcome)
        if streamrip_exec.is_windows_packaged_build():
            # streamrip ships inside the package: never prompt to pip-install
            # it. Instead, guide first-run users straight into Deezer setup.
            GLib.idle_add(self._windows_first_run_setup)
        else:
            GLib.idle_add(self._offer_streamrip_install)
        GLib.idle_add(self._first_run_health_check)

    # ── Préférences ──────────────────────────────────────────────────────────

    def _apply_saved_preferences(self):
        safe_path = (self._dest_folder
                     .replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))
        self.folder_lbl.set_markup(
            f'<span foreground="#FF6B35" size="small">📁  {safe_path}</span>')

        try:
            quality_idx = int(self._config.get("quality_level", 3))
        except (TypeError, ValueError):
            quality_idx = 3
        if 0 <= quality_idx < len(self._quality_checks):
            for i, cb in enumerate(self._quality_checks):
                cb.handler_block_by_func(self._on_quality_toggled)
                cb.set_active(i == quality_idx)
                cb.handler_unblock_by_func(self._on_quality_toggled)

        if self.cb_organize is not None:
            self.cb_organize.handler_block_by_func(self._on_organize_toggled)
            self.cb_organize.set_active(
                bool(self._config.get("organize_library", True)))
            self.cb_organize.handler_unblock_by_func(self._on_organize_toggled)
        if self.cb_playlists_subfolder is not None:
            self.cb_playlists_subfolder.handler_block_by_func(
                self._on_organize_toggled)
            self.cb_playlists_subfolder.set_active(
                bool(self._config.get("playlists_subfolder", True)))
            self.cb_playlists_subfolder.handler_unblock_by_func(
                self._on_organize_toggled)

    def _on_organize_toggled(self, *_):
        self._persist_preferences()

    def _persist_preferences(self):
        self._config["download_folder"] = self._dest_folder
        for i, cb in enumerate(self._quality_checks):
            if cb.get_active():
                self._config["quality_level"] = i
                break
        if self.cb_organize is not None:
            self._config["organize_library"] = self.cb_organize.get_active()
        if self.cb_playlists_subfolder is not None:
            self._config["playlists_subfolder"] = \
                self.cb_playlists_subfolder.get_active()
        try:
            save_config(self._config)
        except OSError as e:
            GLib.idle_add(self._log, f"⚠  Could not save preferences: {e}\n", "error")

    # ── Qualité ──────────────────────────────────────────────────────────────

    def _on_quality_toggled(self, widget, idx):
        if widget.get_active():
            for i, cb in enumerate(self._quality_checks):
                if i != idx:
                    cb.handler_block_by_func(self._on_quality_toggled)
                    cb.set_active(False)
                    cb.handler_unblock_by_func(self._on_quality_toggled)
            self._persist_preferences()

    def _get_quality(self):
        for i, cb in enumerate(self._quality_checks):
            if cb.get_active():
                return QUALITY_VALUES[i]
        return "3"

    # ── Dossiers ─────────────────────────────────────────────────────────────

    def _choose_folder(self, *_):
        dlg = Gtk.FileChooserDialog(
            title="Choose Download Folder", parent=self.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN,   Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            self._dest_folder = dlg.get_filename()
            safe_path = (self._dest_folder
                         .replace("&", "&amp;")
                         .replace("<", "&lt;")
                         .replace(">", "&gt;"))
            self.folder_lbl.set_markup(
                f'<span foreground="#FF6B35" size="small">📁  {safe_path}</span>')
            self._persist_preferences()
        dlg.destroy()

    def _open_folder(self, *_):
        os.makedirs(self._dest_folder, exist_ok=True)
        open_in_file_manager(self._dest_folder)

    def _open_downloads_folder(self, *_):
        folder = self._dest_folder
        if not folder or not os.path.isdir(folder):
            self._show_folder_error(
                "Download folder not found",
                f"The configured download folder does not exist:\n\n{folder}\n\n"
                "Choose a destination folder or run a download to create it.",
            )
            return
        try:
            open_in_file_manager(folder)
        except OSError as exc:
            self._show_folder_error(
                "Could not open download folder",
                f"{folder}\n\n{exc}",
            )

    def _show_folder_error(self, title, detail):
        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )
        dlg.format_secondary_text(detail)
        dlg.run()
        dlg.destroy()

    def _open_log_folder(self, *_):
        log_dir = resolve_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        open_in_file_manager(log_dir)

    # ── Download History ─────────────────────────────────────────────────────

    @staticmethod
    def _history_escape(text):
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _history_status_color(status):
        return {
            "Completed":   "#87a556",
            "Downloading": "#FF6B35",
            "Warning":     "#e0a83b",
            "Failed":      "#e74c3c",
        }.get(status, "#aaaaaa")

    @staticmethod
    def _format_history_title(artist, album):
        artist = (artist or "").strip()
        album = (album or "").strip()
        if artist and album:
            return f"{artist} — {album}"
        return album or artist or ""

    @staticmethod
    def _snapshot_dest_dirs(base):
        try:
            return {name for name in os.listdir(base)
                    if os.path.isdir(os.path.join(base, name))}
        except OSError:
            return set()

    @staticmethod
    def _detect_new_folder(base, snapshot):
        """Return absolute path of the most recent newly-created subdir, or None."""
        try:
            current = AurynApp._snapshot_dest_dirs(base)
            new_names = current - snapshot
            if not new_names:
                return None
            candidates = [os.path.join(base, n) for n in new_names]
            return max(candidates, key=lambda p: os.path.getmtime(p))
        except OSError:
            return None

    def _history_add_entry(self, url):
        entry = {
            "url": url,
            "title": "",
            "status": "Downloading",
            "timestamp": time.strftime("%H:%M:%S"),
            "folder": None,
        }
        self._download_history.insert(0, entry)
        self._history_render()
        return entry

    def _history_set_title(self, entry, title):
        if entry is None or not title:
            return
        if entry.get("title") == title:
            return
        entry["title"] = title
        self._history_render()

    def _history_set_status(self, entry, status, folder=None):
        if entry is None:
            return
        entry["status"] = status
        if folder:
            entry["folder"] = folder
        self._history_render()

    def _history_render(self):
        for child in self.history_listbox.get_children():
            self.history_listbox.remove(child)

        if not self._download_history:
            self.history_empty_label.show()
            return

        self.history_empty_label.hide()
        for entry in self._download_history:
            self.history_listbox.add(self._history_create_row(entry))
        self.history_listbox.show_all()

    def _history_create_row(self, entry):
        row = Gtk.ListBoxRow()
        row.set_can_focus(False)
        row.get_style_context().add_class("history-row")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.set_hexpand(True)

        title_text = entry["title"] or entry["url"]
        title_lbl = Gtk.Label()
        title_lbl.set_halign(Gtk.Align.START)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_lbl.set_max_width_chars(60)
        title_lbl.set_markup(
            f'<span foreground="#e8e8e8" size="small">{self._history_escape(title_text)}</span>'
        )
        left.pack_start(title_lbl, False, False, 0)

        if entry["title"]:
            url_lbl = Gtk.Label()
            url_lbl.set_halign(Gtk.Align.START)
            url_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            url_lbl.set_max_width_chars(60)
            url_lbl.set_markup(
                f'<span foreground="#666666" size="x-small">{self._history_escape(entry["url"])}</span>'
            )
            left.pack_start(url_lbl, False, False, 0)

        info_lbl = Gtk.Label()
        info_lbl.set_halign(Gtk.Align.START)
        status_color = self._history_status_color(entry["status"])
        meta_parts = [
            f'<span foreground="{status_color}" size="small" weight="bold">{entry["status"]}</span>',
            f'<span foreground="#555555" size="x-small">  ·  {entry["timestamp"]}</span>',
        ]
        if entry.get("folder"):
            meta_parts.append(
                f'<span foreground="#555555" size="x-small">  ·  {self._history_escape(entry["folder"])}</span>'
            )
        info_lbl.set_markup("".join(meta_parts))
        info_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        info_lbl.set_max_width_chars(80)
        left.pack_start(info_lbl, False, False, 0)

        box.pack_start(left, True, True, 0)

        if entry["status"] == "Completed" or (
                entry["status"] == "Warning" and entry.get("folder")):
            btn = Gtk.Button(label="Open Folder")
            btn.get_style_context().add_class("neutral-btn")
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect("clicked", self._history_open_entry_folder, entry)
            box.pack_end(btn, False, False, 0)

        row.add(box)
        return row

    def _history_open_entry_folder(self, _button, entry):
        folder = entry.get("folder")
        if not folder or not os.path.isdir(folder):
            self._show_folder_error(
                "Folder not found",
                "The download folder is no longer available:\n\n"
                f"{folder or '(unknown)'}\n\n"
                "It may have been moved or deleted since the download finished.",
            )
            return
        try:
            open_in_file_manager(folder)
        except OSError as exc:
            self._show_folder_error(
                "Could not open folder",
                f"{folder}\n\n{exc}",
            )

    # ── Download Queue ───────────────────────────────────────────────────────

    @staticmethod
    def _queue_status_color(status):
        return {
            "Queued":      "#888888",
            "Downloading": "#FF6B35",
            "Completed":   "#87a556",
            "Warning":     "#e0a83b",
            "Failed":      "#e74c3c",
        }.get(status, "#aaaaaa")

    def _is_downloading(self):
        return self._process is not None and self._process.poll() is None

    def _on_add_to_queue(self, *_):
        url = self.url_entry.get_text().strip()
        if not url:
            self._set_status("⚠   Paste a URL before queueing.", "error")
            return
        self._queue_enqueue_url(url)
        self.url_entry.set_text("")
        if not self._is_downloading():
            self._queue_start_next()

    def _queue_enqueue_url(self, url):
        item = {
            "id": self._queue_seq,
            "url": url,
            "title": "",
            "status": "Queued",
        }
        self._queue_seq += 1
        self._queue.append(item)
        self._queue_render()

    def _queue_set_status(self, item, status):
        if item is None:
            return
        item["status"] = status
        self._queue_render()

    def _queue_set_title(self, item, title):
        if item is None or not title:
            return
        if item.get("title") == title:
            return
        item["title"] = title
        self._queue_render()

    def _queue_first_pending(self):
        for item in self._queue:
            if item["status"] == "Queued":
                return item
        return None

    def _queue_start_next(self):
        item = self._queue_first_pending()
        if item is None:
            return
        item["status"] = "Downloading"
        self._current_queue_item = item
        self._queue_render()
        self._begin_download(item["url"])

    def _on_clear_queue(self, *_):
        self._queue = [it for it in self._queue if it["status"] == "Downloading"]
        self._queue_render()

    def _on_remove_queue_item(self, _btn, item):
        if item.get("status") == "Downloading":
            return
        if item in self._queue:
            self._queue.remove(item)
            self._queue_render()

    def _queue_render(self):
        for child in self.queue_listbox.get_children():
            self.queue_listbox.remove(child)
        if not self._queue:
            self.queue_empty_label.show()
            self.btn_clear_queue.set_sensitive(False)
            return
        self.queue_empty_label.hide()
        self.btn_clear_queue.set_sensitive(
            any(it["status"] != "Downloading" for it in self._queue)
        )
        for item in self._queue:
            self.queue_listbox.add(self._queue_create_row(item))
        self.queue_listbox.show_all()

    def _queue_create_row(self, item):
        row = Gtk.ListBoxRow()
        row.set_can_focus(False)
        row.get_style_context().add_class("history-row")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.set_hexpand(True)

        title_text = item["title"] or item["url"]
        title_lbl = Gtk.Label()
        title_lbl.set_halign(Gtk.Align.START)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_lbl.set_max_width_chars(60)
        title_lbl.set_markup(
            f'<span foreground="#e8e8e8" size="small">{self._history_escape(title_text)}</span>'
        )
        left.pack_start(title_lbl, False, False, 0)

        if item["title"]:
            url_lbl = Gtk.Label()
            url_lbl.set_halign(Gtk.Align.START)
            url_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            url_lbl.set_max_width_chars(60)
            url_lbl.set_markup(
                f'<span foreground="#666666" size="x-small">{self._history_escape(item["url"])}</span>'
            )
            left.pack_start(url_lbl, False, False, 0)

        status_color = self._queue_status_color(item["status"])
        info_lbl = Gtk.Label()
        info_lbl.set_halign(Gtk.Align.START)
        info_lbl.set_markup(
            f'<span foreground="{status_color}" size="small" weight="bold">{item["status"]}</span>'
        )
        left.pack_start(info_lbl, False, False, 0)

        box.pack_start(left, True, True, 0)

        if item["status"] == "Queued":
            btn = Gtk.Button(label="Remove")
            btn.get_style_context().add_class("neutral-btn")
            btn.set_valign(Gtk.Align.CENTER)
            btn.connect("clicked", self._on_remove_queue_item, item)
            box.pack_end(btn, False, False, 0)

        row.add(box)
        return row

    # ── Download ─────────────────────────────────────────────────────────────

    def _on_download(self, *_):
        url = self.url_entry.get_text().strip()
        if not url:
            self._set_status("⚠   Please paste a URL first.", "error")
            return
        self._begin_download(url)

    def _begin_download(self, url):
        ok, issues = self._run_preflight_checks(auto_fix=False)
        if not ok:
            self._set_status("❌  Setup issue detected — open Setup.", "error")
            self._log("❌  Preflight checks failed:\n", "error")
            for issue in issues:
                self._log(f"   • {issue}\n", "error")
            if self._current_queue_item is not None:
                self._queue_set_status(self._current_queue_item, "Failed")
                self._current_queue_item = None
            return
        os.makedirs(self._dest_folder, exist_ok=True)
        self._dest_dirs_snapshot    = self._snapshot_dest_dirs(self._dest_folder)
        self._current_history_entry = self._history_add_entry(url)
        self.btn_download.set_sensitive(False)
        self.btn_stop.show()
        self.btn_stop.set_sensitive(True)
        self.progress_bar.set_fraction(0)
        self._clear_log()
        self._reset_meta()
        self._track_done       = 0
        self._total_tracks     = 0
        self._last_known_error = None
        self._album_meta          = None
        self._active_is_playlist  = url_is_playlist(url)
        self._active_quality      = None
        self._reset_streamrip_signals()
        self._set_status("⏳  Fetching album info...", "info")
        self._set_lyrics('<span foreground="#555555"><i>Lyrics appear here once a track is identified.</i></span>')
        quality = self._get_quality()
        threading.Thread(target=self._thread_main, args=(url, quality), daemon=True).start()

    def _on_stop(self, *_):
        self._queue_stopped_by_user = True
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self._log("⏹   Download stopped by user.\n", "error")
            self._set_status("Stopped.", "error")
        self.btn_stop.set_sensitive(False)

    def _thread_main(self, url, quality):
        if deezer.is_deezer_url(url):
            url = self._prepare_deezer_url(url)
            if url is None:
                return  # pre-check failed; UI/queue already updated
        # The (possibly normalised / resolved) URL is now final; refine the
        # album-vs-playlist routing used by post-download organisation.
        self._active_is_playlist = url_is_playlist(url)
        service, item_id = detect_service_and_id(url)
        if service == "qobuz" and item_id:
            GLib.idle_add(self._set_status, "⏳  Fetching metadata...", "info")
            data = fetch_qobuz_meta(item_id)
            if data and not data.get("status") == "error":
                GLib.idle_add(self._apply_qobuz_meta, data)
        elif service == "deezer" and item_id:
            GLib.idle_add(self._set_status, "⏳  Fetching metadata...", "info")
            data = fetch_deezer_album(item_id)
            if data and not data.get("error"):
                GLib.idle_add(self._apply_deezer_meta, data)
        elif service == "deezer_track" and item_id:
            GLib.idle_add(self._set_status, "⏳  Fetching metadata...", "info")
            data = fetch_deezer_track_album(item_id)
            if data and not data.get("error"):
                GLib.idle_add(self._apply_deezer_meta, data)
                # For single track, fetch lyrics immediately
                artist = data.get("artist", {}).get("name")
                title = data.get("title")
                if artist and title:
                    threading.Thread(target=self._fetch_and_apply_lyrics, args=(artist, title), daemon=True).start()
        if deezer.is_deezer_url(url) and not self._deezer_config_ready():
            return  # "Deezer not configured" — UI/queue already updated
        GLib.idle_add(self._set_status, "⏳  Preparing download...", "info")
        self._run_download(url, quality)

    # ── Deezer pre-checks ──────────────────────────────────────────────────────
    #
    # streamrip only accepts a narrow set of Deezer URL forms and silently
    # produces confusing per-track failures otherwise. These helpers normalize /
    # resolve / validate the URL and confirm an ARL is configured BEFORE
    # streamrip is spawned, so a bad link or missing credential fails fast with
    # guidance instead of a mid-download crash. They run in the download worker
    # thread; all UI work is marshalled back via GLib.idle_add.

    def _prepare_deezer_url(self, url):
        """Normalize / resolve / validate a Deezer URL before downloading.

        Returns the URL to hand to streamrip, or None if the download was
        aborted (UI + queue already updated by ``_finish_precheck_failed``).
        """
        info = deezer.classify_deezer_url(url)
        normalized = info["normalized"]

        if info["kind"] == deezer.SHORT_LINK:
            GLib.idle_add(
                self._log,
                "🔗  Detected a Deezer share link — resolving to the full "
                "deezer.com URL…\n", "info")
            resolved, err = deezer.resolve_short_link(url)
            if resolved:
                GLib.idle_add(self._log, f"🔗  Resolved to: {resolved}\n", "info")
                normalized = resolved
                info = deezer.classify_deezer_url(resolved)
            else:
                detail = f" ({err})" if err else ""
                GLib.idle_add(
                    self._finish_precheck_failed,
                    "❌  Could not resolve this Deezer share link.",
                    [f"streamrip cannot open share links directly{detail}.",
                     "💡  Open the link in your browser and paste the final "
                     "deezer.com album / track / playlist URL instead."])
                return None

        if normalized != url:
            GLib.idle_add(self._log,
                          f"🔧  Using Deezer URL: {normalized}\n", "info")

        if not deezer.streamrip_will_accept(normalized):
            GLib.idle_add(
                self._finish_precheck_failed,
                "❌  Unsupported Deezer URL — see the log.",
                ["streamrip only accepts deezer.com album / track / playlist / "
                 "artist URLs (and deezer.page.link links).",
                 "💡  Open the link in your browser and paste the final "
                 "deezer.com URL."])
            return None

        return normalized

    def _deezer_config_ready(self):
        """True if streamrip is configured for Deezer; else abort with guidance.

        Surfaces a clear "Deezer not configured" message before the download
        instead of letting streamrip fail later. Never reads or logs the ARL.
        """
        st = deezer.deezer_config_status(self._streamrip_config_path())
        if st["ready"]:
            return True
        guidance = ["Deezer downloads need an ARL cookie saved in streamrip's "
                    "config.toml."]
        guidance += [f"• {p}" for p in st["problems"]]
        guidance.append("💡  Open Setup → Deezer, paste your ARL and Save, then "
                        "try again.")
        GLib.idle_add(
            self._finish_precheck_failed,
            "🔐  Deezer not configured — add your ARL in Setup.", guidance)
        return False

    def _finish_precheck_failed(self, status_msg, log_lines=None):
        """Abort a download before streamrip is spawned; reset UI + queue.

        Mirrors the tail of ``_finish`` (button reset, history/queue status,
        queue advance) for failures detected during the pre-flight phase, when
        there is no streamrip process to wait on. Runs on the GTK thread.
        """
        self._set_status(status_msg, "error")
        self._log("\n" + status_msg + "\n", "error")
        for line in (log_lines or []):
            self._log(f"   {line}\n", "info")
        self._history_set_status(self._current_history_entry, "Failed")
        self._queue_set_status(self._current_queue_item, "Failed")
        self._current_history_entry = None
        self._current_queue_item = None
        self.btn_download.set_sensitive(True)
        self.btn_stop.hide()
        self.speed_lbl.set_markup("")
        if self._queue_stopped_by_user:
            self._queue_stopped_by_user = False
        else:
            self._queue_start_next()
        return False

    # ── Métadonnées ───────────────────────────────────────────────────────────
    #
    # PROTECTED UX SURFACE — the right-side album sidebar (cover art + artist /
    # album / quality / track count / UPC / release date) is a critical,
    # user-facing feature. It must NEVER crash the UI or the streamrip log
    # pump, even with partial/None API payloads or a renamed .ui widget.
    #
    # Rules for anyone touching this section:
    #   * Route every sidebar text write through self._set_meta(); never call
    #     a label's .set_markup() directly from parsing code.
    #   * Parse/normalize API payloads in core.metadata (GTK-free, tested).
    #   * If cover art is missing/fails, leave the existing placeholder.
    # See tests/test_metadata.py for the regression guarantees.

    def _get_meta_text(self, key):
        """Read a sidebar label's current text, tolerating a missing widget."""
        widget = self._meta.get(key)
        if widget is None:
            return ""
        try:
            return widget.get_text()
        except Exception:
            return ""

    def _set_meta(self, key, value, overwrite=True, limit=metadata.META_MAX_LEN):
        """Safely write *value* into the sidebar label for *key*.

        Defensive by design:
          * unknown key / renamed-or-missing widget  -> no-op (never raises)
          * empty / falsy value                      -> keep placeholder
          * overwrite=False                          -> only fill an empty
            field (matches the log-scraping "don't clobber" behaviour)

        A single broken widget must not take down metadata parsing or the
        streamrip output pump, so the GTK call is guarded too.
        """
        markup = metadata.build_meta_markup(value, limit)
        if markup is None:
            return
        widget = self._meta.get(key)
        if widget is None:
            return
        if not overwrite:
            current = self._get_meta_text(key)
            if current not in ("—", ""):
                return
        try:
            widget.set_markup(markup)
        except Exception:
            pass

    def _remember_album_meta(self, fields):
        """Stash untruncated album artist/title for post-download organisation.

        The sidebar labels are truncated for display, so the library organiser
        relies on these full values to build folder names. Never raises on a
        partial payload.
        """
        try:
            artist = (fields.get("artist") or "").strip()
            album = (fields.get("album") or "").strip()
        except AttributeError:
            return
        if artist or album:
            self._album_meta = {"artist": artist, "album": album}

    def _apply_deezer_meta(self, data):
        fields = metadata.deezer_album_fields(data)
        self._remember_album_meta(fields)
        # Deezer values are kept slightly shorter to fit the historical layout.
        self._set_meta("Album Artist",  fields["artist"],       limit=28)
        self._set_meta("Album",         fields["album"],        limit=28)
        self._set_meta("Total Tracks",  fields["total_tracks"], limit=28)
        self._set_meta("UPC",           fields["upc"],          limit=28)
        self._set_meta("Release Date",  fields["release_date"], limit=28)
        self._set_meta("Album Quality", fields["quality"],      limit=28)
        title = self._format_history_title(fields["artist"], fields["album"])
        self._history_set_title(self._current_history_entry, title)
        self._queue_set_title(self._current_queue_item, title)
        if fields["cover_url"]:
            threading.Thread(target=self._load_cover,
                              args=(fields["cover_url"],), daemon=True).start()

    def _apply_qobuz_meta(self, data):
        fields = metadata.qobuz_album_fields(data)
        self._remember_album_meta(fields)
        self._set_meta("Album Artist",  fields["artist"])
        self._set_meta("Album",         fields["album"])
        self._set_meta("Total Tracks",  fields["total_tracks"])
        self._set_meta("UPC",           fields["upc"])
        self._set_meta("Release Date",  fields["release_date"])
        self._set_meta("Album Quality", fields["quality"])
        title = self._format_history_title(fields["artist"], fields["album"])
        self._history_set_title(self._current_history_entry, title)
        self._queue_set_title(self._current_queue_item, title)
        if fields["cover_url"]:
            threading.Thread(
                target=self._load_cover_with_fallback,
                args=(fields["cover_url"], fields["cover_fallback"]),
                daemon=True,
            ).start()

    def _set_cover_present_label(self):
        """Brighten the caption to signal that real cover art is shown."""
        if self.cover_lbl is None:
            return
        try:
            self.cover_lbl.set_markup(
                '<span foreground="#888888" size="small" letter_spacing="200">COVER</span>')
        except Exception:
            pass

    def _show_cover_pixbuf(self, pb):
        """Display downloaded cover art, or fall back to the placeholder.

        Always leaves the sidebar in a stable state: a successful pixbuf is
        shown with the brightened caption; a failure keeps the existing
        neutral placeholder tile and caption rather than a blank slot.
        """
        if pb and self.cover_img is not None:
            try:
                self.cover_img.set_from_pixbuf(pb)
                self._set_cover_present_label()
                return
            except Exception:
                pass
        self._set_placeholder_cover()
        self._set_cover_placeholder_label()

    def _load_cover_with_fallback(self, url1, url2):
        pb = download_cover(url1, size=185)
        if not pb:
            pb = download_cover(url2, size=185)
        GLib.idle_add(self._show_cover_pixbuf, pb)

    def _load_cover(self, cover_url):
        pb = download_cover(cover_url, size=185)
        GLib.idle_add(self._show_cover_pixbuf, pb)

    # ── Lancement streamrip ───────────────────────────────────────────────────

    def _streamrip_cmd(self):
        """Resolve the streamrip command to spawn, as an argv list (or None).

        Search order (see core.streamrip_exec): streamrip bundled inside a
        packaged Windows build, then an explicitly configured path, then the
        system PATH / common install locations. On a packaged Windows build the
        returned argv is the multi-call form that runs the bundled streamrip in
        Auryn's own frozen interpreter, so users never install Python/streamrip.
        """
        configured = None
        try:
            configured = self._config.get("streamrip_path")
        except Exception:
            configured = None
        if not configured:
            configured = (os.environ.get("AURYN_STREAMRIP")
                          or os.environ.get("AURYN_RIP"))
        return streamrip_exec.get_streamrip_executable(configured_path=configured)

    def _find_rip_path(self):
        """Back-compat shim: the resolved command's first element, or None.

        Existing call sites use this for truthiness ("is streamrip available?")
        and display. Spawn sites use :meth:`_streamrip_cmd` to get the full argv.
        """
        cmd = self._streamrip_cmd()
        return cmd[0] if cmd else None

    def _streamrip_label(self, cmd=None):
        """Display label for the resolved streamrip command (never a secret)."""
        if cmd is None:
            cmd = self._streamrip_cmd()
        return streamrip_exec.describe_streamrip_command(cmd)

    def _ensure_streamrip_config(self):
        """Create streamrip's config.toml if missing so credentials can be saved.

        On a packaged Windows build streamrip is bundled, so `config reset`
        works without any user-installed tooling. Returns True if the config
        exists afterwards. Never raises.
        """
        cfg = self._streamrip_config_path()
        if os.path.exists(cfg):
            return True
        cmd = self._streamrip_cmd()
        if not cmd:
            return False
        try:
            os.makedirs(os.path.dirname(cfg), exist_ok=True)
        except OSError:
            pass
        creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         if IS_WINDOWS else 0)
        try:
            # stdin=DEVNULL so a prompt can never block the GTK thread.
            subprocess.run(cmd + ["config", "reset"], capture_output=True,
                           text=True, timeout=30, stdin=subprocess.DEVNULL,
                           creationflags=creationflags)
        except Exception:
            pass
        return os.path.exists(cfg)

    def _check_dest_writable(self):
        try:
            os.makedirs(self._dest_folder, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self._dest_folder, delete=True):
                pass
            return True
        except Exception:
            return False

    def _run_preflight_checks(self, auto_fix=False):
        issues = []
        rip_cmd = self._streamrip_cmd()
        if not rip_cmd:
            if streamrip_exec.is_windows_packaged_build():
                issues.append(
                    "Bundled streamrip is missing from this Auryn package — "
                    "the download tool could not be located inside the app."
                )
            elif IS_WINDOWS:
                issues.append(
                    "streamrip not found — rip.exe must be installed and in PATH. "
                    "Install via: pipx install streamrip (or: pip install streamrip), "
                    "then open a new terminal to refresh PATH."
                )
            else:
                issues.append("streamrip (rip) is not installed or not in PATH.")

        cfg_path = os.path.join(resolve_config_dir(), "config.toml")
        if not os.path.exists(cfg_path):
            if auto_fix and rip_cmd:
                try:
                    result = subprocess.run(rip_cmd + ["config", "reset"], capture_output=True, text=True)
                    if result.returncode != 0:
                        issues.append("Unable to generate streamrip config automatically.")
                except Exception:
                    issues.append("Unable to run `rip config reset` automatically.")
            if not os.path.exists(cfg_path):
                issues.append(
                    f"streamrip config.toml not found at: {cfg_path} — run: rip config reset"
                )

        if not self._check_dest_writable():
            issues.append(f"Destination is not writable: {self._dest_folder}")

        return (len(issues) == 0, issues)

    def _show_first_launch_welcome(self):
        body = (
            "The setup wizard will help you configure:\n"
            "  • Download folder\n"
            "  • streamrip credentials and config\n\n"
        )
        if streamrip_exec.is_windows_packaged_build():
            body += (
                "streamrip is included in this Auryn package — no separate "
                "Python or streamrip install is required."
            )
        elif self._find_rip_path() is not None:
            body += "streamrip (rip) was detected on your system."
        else:
            body += (
                "streamrip (rip) was not found.\n"
                "Install it with:  pip install streamrip"
            )

        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="Welcome to Auryn — let's get you set up.",
        )
        dlg.format_secondary_text(body)
        dlg.add_button("Get Started", Gtk.ResponseType.OK)
        dlg.run()
        dlg.destroy()
        return False

    def _windows_first_run_setup(self):
        """Packaged Windows first-run: open Deezer setup if no ARL is saved.

        streamrip is bundled, so the only thing a new user must do is paste a
        Deezer ARL. Show Setup proactively instead of letting the first
        download fail. The ARL itself is never logged or displayed.
        """
        cfg = self._streamrip_config_path()
        try:
            arl_present = deezer.deezer_config_status(cfg).get("arl_present")
        except Exception:
            arl_present = False
        if arl_present:
            return False

        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="Set up Deezer to start downloading.",
        )
        dlg.format_secondary_text(
            "Auryn includes everything it needs to download — no Python, pip "
            "or streamrip install required.\n\n"
            "Deezer is the recommended service: paste your ARL token and "
            "you're ready. Your ARL is written only to streamrip's config "
            "file — Auryn never shows or logs it."
        )
        later_btn = dlg.add_button("Later", Gtk.ResponseType.CANCEL)
        setup_btn = dlg.add_button("Set up Deezer", Gtk.ResponseType.OK)
        later_btn.get_style_context().add_class("neutral-btn")
        setup_btn.get_style_context().add_class("neutral-btn")
        dlg.set_default_response(Gtk.ResponseType.OK)
        response = dlg.run()
        dlg.destroy()

        if response == Gtk.ResponseType.OK:
            self._show_credentials_dialog()
        return False

    def _offer_streamrip_install(self):
        """When `rip` is missing, prompt the user to install streamrip via pip.

        Runs once at startup. Skipping is non-blocking; installing is opt-in
        and surfaces success or failure clearly. Returns False so GLib.idle_add
        does not reschedule it.
        """
        if self._find_rip_path():
            return False

        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="streamrip is required",
        )
        dlg.format_secondary_text(
            "Auryn uses the `rip` command from the streamrip package, "
            "but it was not found on your system.\n\n"
            "Would you like to install it now? This will run:\n"
            f"    {sys.executable} -m pip install --user streamrip"
        )
        skip_btn = dlg.add_button("Skip", Gtk.ResponseType.CANCEL)
        install_btn = dlg.add_button("Install streamrip", Gtk.ResponseType.OK)
        skip_btn.get_style_context().add_class("neutral-btn")
        install_btn.get_style_context().add_class("neutral-btn")
        dlg.set_default_response(Gtk.ResponseType.OK)

        response = dlg.run()
        dlg.destroy()

        if response == Gtk.ResponseType.OK:
            self._install_streamrip()
        else:
            self._log("ℹ  streamrip install skipped — you can install it later "
                      "via: pip install --user streamrip\n", "info")
        return False

    def _install_streamrip(self):
        """Run `pip install --user streamrip` in a worker thread, with a modal
        progress dialog. Re-checks for `rip` once pip exits."""
        progress = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="Installing streamrip…",
        )
        progress.format_secondary_text(
            "Running: pip install --user streamrip\n\n"
            "This may take a minute. Please wait."
        )
        close_btn = progress.add_button("Close", Gtk.ResponseType.CLOSE)
        close_btn.get_style_context().add_class("neutral-btn")
        close_btn.set_sensitive(False)
        progress.show_all()

        self._log(f"⏳  Installing streamrip via {sys.executable} -m pip "
                  "install --user streamrip…\n", "info")

        cmd = [sys.executable, "-m", "pip", "install", "--user", "streamrip"]

        def worker():
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True)
                GLib.idle_add(
                    self._finish_streamrip_install, progress, close_btn,
                    proc.returncode, proc.stdout or "", proc.stderr or "",
                )
            except Exception as exc:
                GLib.idle_add(
                    self._finish_streamrip_install, progress, close_btn,
                    -1, "", f"Could not launch pip: {exc}",
                )

        threading.Thread(target=worker, daemon=True).start()
        progress.run()
        progress.destroy()

    def _finish_streamrip_install(self, progress, close_btn, returncode,
                                  stdout, stderr):
        """Update the progress dialog with the pip outcome and re-check rip."""
        rip_path = self._find_rip_path()
        success = (returncode == 0) and bool(rip_path)

        if success:
            progress.set_property("text", "streamrip installed")
            progress.set_property(
                "secondary-text",
                f"`rip` is now available at:\n{rip_path}",
            )
            progress.set_property("message-type", Gtk.MessageType.INFO)
            self._set_status("✅  streamrip installed.", "ok")
            self._log(f"✅  streamrip installed. rip detected at {rip_path}\n",
                      "ok")
        else:
            if returncode == 0 and not rip_path:
                detail = ("pip reported success but `rip` was not detected.\n"
                          "It may have been installed to a folder not on PATH.\n"
                          "Try opening a new terminal session, or install via "
                          "pipx instead.")
            else:
                tail = (stderr or stdout).strip().splitlines()[-6:]
                detail = "pip install failed.\n\n" + "\n".join(tail) \
                    if tail else "pip install failed with no output."
            progress.set_property("text", "streamrip install failed")
            progress.set_property("secondary-text", detail)
            progress.set_property("message-type", Gtk.MessageType.ERROR)
            self._set_status("❌  streamrip install failed.", "error")
            self._log("❌  streamrip install failed.\n", "error")
            for line in detail.splitlines():
                if line.strip():
                    self._log(f"   {line}\n", "info")

        close_btn.set_sensitive(True)
        close_btn.grab_focus()
        return False

    def _first_run_health_check(self):
        ok, issues = self._run_preflight_checks(auto_fix=False)
        if ok:
            self._set_status("✅  Setup check passed — ready.", "ok")
        else:
            self._set_status("⚠  Setup incomplete — click Setup.", "error")
            self._log("⚠  Startup checks found issues:\n", "info")
            for issue in issues:
                self._log(f"   • {issue}\n", "info")
        return False

    def _show_setup_wizard(self, *_):
        ok, issues = self._run_preflight_checks(auto_fix=False)
        if ok:
            body = "Everything looks good.\n\nYou can start downloads safely."
            status = "✅ Setup OK"
        else:
            body = "Issues detected:\n- " + "\n- ".join(issues)
            status = "⚠ Setup needs attention"

        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            flags=0,
            message_type=Gtk.MessageType.INFO if ok else Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=status,
        )
        dlg.format_secondary_text(body)
        if not ok:
            dlg.add_button("Auto-fix", 1)
        dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        response = dlg.run()
        dlg.destroy()

        if response == 1:
            fixed_ok, fixed_issues = self._run_preflight_checks(auto_fix=True)
            if fixed_ok:
                self._set_status("✅  Setup auto-fix completed.", "ok")
                self._log("✅  Setup auto-fix completed successfully.\n", "ok")
            else:
                self._set_status("❌  Setup still incomplete.", "error")
                self._log("❌  Setup auto-fix could not solve all issues:\n", "error")
                for issue in fixed_issues:
                    self._log(f"   • {issue}\n", "error")

    def _apply_stored_credentials(self, cfg):
        """Migrate any legacy ~/.config/Auryn/accounts.json into config.toml.

        This is a one-way migration of an old Auryn storage format. It writes
        through the atomic, section-scoped writer and deliberately **never
        touches the [tidal] section**: TIDAL tokens are owned and refreshed
        by streamrip itself, and rewriting them is exactly what broke auth
        persistence. TIDAL must be (re)authenticated via the TIDAL Setup
        flow, not migrated from a flat token file.
        """
        acc_path = os.path.join(resolve_auryn_data_dir(), "accounts.json")
        if not os.path.exists(acc_path):
            return

        try:
            with open(acc_path, 'r', encoding="utf-8") as f:
                acc = json.load(f)
        except Exception as e:
            GLib.idle_add(self._log, f"⚠  Could not read accounts.json: {e}\n", "error")
            return

        # canonical key -> (section, value, accepted key names) using
        # streamrip's real schema keys, written via the atomic alias-aware
        # section writer. TIDAL is intentionally absent.
        plan = []
        if isinstance(acc.get("qobuz"), dict):
            q = acc["qobuz"]
            updates = {}
            if q.get("email"):
                updates["email"] = q["email"]
            if q.get("password"):
                updates["password"] = q["password"]
            if updates:
                plan.append(("qobuz", updates,
                             {"email": ["email", "email_or_userid"],
                              "password": ["password", "password_or_token"]}))
        if isinstance(acc.get("deezer"), dict) and acc["deezer"].get("arl"):
            plan.append(("deezer", {"arl": acc["deezer"]["arl"]},
                         {"arl": ["arl"]}))
        if (isinstance(acc.get("soundcloud"), dict)
                and acc["soundcloud"].get("oauth_token")):
            plan.append(("soundcloud",
                         {"oauth_token": acc["soundcloud"]["oauth_token"]},
                         {"oauth_token": ["oauth_token"]}))

        if "tidal" in acc:
            self._auth_log(
                "🔐  Skipping legacy TIDAL credentials in accounts.json — "
                "TIDAL tokens are managed by streamrip; use TIDAL Setup to "
                "re-authenticate.\n", "info")

        if not plan:
            return

        GLib.idle_add(self._log, "🔐  Migrating stored credentials...\n", "info")
        for section, updates, aliases in plan:
            ok, err = self._write_streamrip_section(
                cfg, section, updates, aliases)
            if not ok:
                self._auth_log(
                    f"⚠  Could not migrate {section} credentials: {err}\n",
                    "error")

    def _run_download(self, url, quality):
        cfg = self._streamrip_config_path()
        db = os.path.join(os.path.dirname(cfg), "downloads.db")

        self._active_url = url
        self._active_quality = quality
        self._tidal_auth_required = False
        self._tidal_auth_corrupted = False
        self._tb_noise_notified = False
        self._deezer_provider_notified = False
        self._cfg_fingerprint_pre = None

        if self.cb_clear_cache.get_active() and os.path.exists(db):
            try:
                os.remove(db)
                GLib.idle_add(self._log, "🧹  Cache cleared.\n", "info")
            except Exception:
                pass

        self._auth_log(f"🗂  streamrip config: {cfg}\n", "info")

        if os.path.exists(cfg):
            if tidal_auth.is_tidal_url(url):
                self._log_tidal_preflight(cfg)
                # Pre-empt the known streamrip crash: a saved session with a
                # present access_token but empty/invalid token_expiry makes
                # streamrip raise ValueError on float(token_expiry) and loop
                # on re-login. Stop here and offer a one-click repair instead
                # of spawning streamrip just to watch it crash.
                v = tidal_auth.validate_tidal_auth_state(cfg)
                if v["access_present"] and v["expiry_value_error"]:
                    self._auth_log(
                        "🔐  TIDAL auth data is corrupted/incomplete "
                        "(token_expiry is "
                        f"{v['expiry_state']}); skipping the download to "
                        "avoid a streamrip crash loop.\n", "error")
                    GLib.idle_add(self._finish_tidal_corrupted)
                    return
            self._cfg_fingerprint_pre = tidal_auth.config_fingerprint(cfg)

            self._apply_stored_credentials(cfg)

            edits = [
                {"section": "downloads", "key": "folder",
                 "value": self._dest_folder, "quote": True},
                {"section": "qobuz", "key": "use_auth_token",
                 "value": "true", "quote": False},
            ]
            # Each service implements only part of streamrip's 0–4 quality
            # scale; writing a value above a service's maximum makes streamrip
            # index its fixed quality table out of bounds and crash ("list
            # index out of range") on every track (Deezer is the worst case,
            # max 2). Clamp every section to the range core.quality says the
            # service supports, so a Max/Hi-Res selection downgrades cleanly
            # instead of failing. The rules live in core.quality so they are
            # defined once rather than duplicated per call site.
            for svc in ("qobuz", "tidal", "deezer", "soundcloud"):
                edits.append({"section": svc, "key": "quality",
                              "value": str(qual.clamp_quality(svc, quality)),
                              "quote": False})

            active_service = qual.service_for_url(url)
            if active_service and qual.quality_was_clamped(active_service, quality):
                GLib.idle_add(
                    self._log,
                    "ℹ️  " + qual.clamp_message(active_service, quality) + "\n",
                    "info")
            elif active_service and qual.is_experimental(active_service, quality):
                GLib.idle_add(
                    self._log,
                    "ℹ️  {} {} is experimental in streamrip.\n".format(
                        qual.service_display_name(active_service),
                        qual.quality_label(
                            qual.clamp_quality(active_service, quality))),
                    "info")

            ok, err, changed = tidal_auth.apply_streamrip_config_updates(
                cfg, edits)
            if not ok:
                self._auth_log(
                    f"⚠  Could not update streamrip config safely: {err}\n",
                    "error")
            elif changed:
                self._auth_log(
                    "🗂  Updated config.toml sections "
                    f"[{', '.join(changed)}] (TIDAL auth left untouched).\n",
                    "info")

            if tidal_auth.AUTH_DEBUG and tidal_auth.is_tidal_url(url):
                for ln in tidal_auth.auth_debug_report(cfg).split("\n"):
                    self._auth_log(ln + "\n", "dim")
        else:
            self._auth_log(
                "⚠  streamrip config.toml not found — run TIDAL Setup or "
                "`rip config reset` first.\n", "error")

        GLib.idle_add(self._log, f"🌐  URL     : {url}\n", "info")
        GLib.idle_add(self._log, f"🎵  Quality : {quality} | Dest : {self._dest_folder}\n", "info")
        GLib.idle_add(self._log, "─" * 60 + "\n", "dim")

        rip_cmd = self._streamrip_cmd()

        if not rip_cmd:
            if streamrip_exec.is_windows_packaged_build():
                GLib.idle_add(self._log,
                    "❌  Bundled streamrip is missing from this Auryn package.\n"
                    "    The download tool could not be located inside the app.\n", "error")
            elif IS_WINDOWS:
                GLib.idle_add(self._log,
                    "❌  streamrip not found — rip.exe must be in PATH.\n"
                    "    Install: pipx install streamrip  (or: pip install streamrip)\n"
                    "    After install, open a new terminal so PATH is updated.\n", "error")
            else:
                GLib.idle_add(self._log,
                    "❌  streamrip (rip) not found!\n"
                    "    Install: pipx install streamrip\n"
                    "    Then:    rip config reset\n", "error")
            GLib.idle_add(self._finish, False)
            return

        GLib.idle_add(self._log, f"🔧  Using: {self._streamrip_label(rip_cmd)}\n", "info")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["TERM"] = "xterm-256color"
        env["FORCE_COLOR"] = "1"
        # streamrip prints Unicode track/artist names to stdout. On Windows the
        # default process encoding is cp1252, so streamrip itself raises
        # UnicodeEncodeError ('charmap' codec). Forcing UTF-8 mode in the child
        # is a no-op on Linux and prevents the crash on Windows.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        if IS_WINDOWS:
            self._run_download_windows(rip_cmd, url, env)
            return

        master_fd, slave_fd = pty.openpty()

        try:
            self._process = subprocess.Popen(
                rip_cmd + ["url", url],
                stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                close_fds=True, env=env,
            )
        except Exception as e:
            GLib.idle_add(self._log, f"❌  Could not start rip: {e}\n", "error")
            GLib.idle_add(self._finish, False)
            os.close(master_fd)
            os.close(slave_fd)
            return

        GLib.idle_add(self._set_status, "🚀  Downloading...", "info")
        os.close(slave_fd)
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        import select
        buf = ""
        while True:
            if self._process.poll() is not None:
                try:
                    remaining = os.read(master_fd, 65536).decode("utf-8", errors="replace")
                    buf += remaining
                except Exception:
                    pass
                break
            try:
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    try:
                        data = os.read(master_fd, 4096).decode("utf-8", errors="replace")
                        buf += data
                    except OSError:
                        break
            except (select.error, ValueError):
                break

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                clean = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', line)
                clean = re.sub(r'\x1b\][^\x07]*\x07', '', clean)
                clean = re.sub(r'\r', '', clean)
                if clean.strip():
                    GLib.idle_add(self._parse_line, clean + "\n")
                    if re.search(r'Track Download Done', clean, re.I):
                        self._track_done += 1
                        if self._total_tracks > 0:
                            GLib.idle_add(self.progress_bar.set_fraction,
                                          min(self._track_done / self._total_tracks, 1.0))
                            GLib.idle_add(self._set_status,
                                          f"💾  Saving files ({self._track_done}/{self._total_tracks})...", "info")
                        else:
                            GLib.idle_add(self._set_status, "💾  Saving files...", "info")
                    m = re.search(r"([\d.]+\s*[KMG]B/s)", clean)
                    if m:
                        GLib.idle_add(self.speed_lbl.set_markup,
                            f'<span foreground="#FF6B35" size="small">⬇  {m.group(1)}  </span>')

        try:
            os.close(master_fd)
        except Exception:
            pass

        self._process.wait()
        GLib.idle_add(self._finish, self._process.returncode == 0)

    def _run_download_windows(self, rip_cmd, url, env):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                rip_cmd + ["url", url],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creation_flags,
            )
        except Exception as e:
            GLib.idle_add(self._log, f"❌  Could not start rip: {e}\n", "error")
            GLib.idle_add(self._finish, False)
            return

        GLib.idle_add(self._set_status, "🚀  Downloading...", "info")

        try:
            for line in self._process.stdout:
                clean = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', line)
                clean = re.sub(r'\x1b\][^\x07]*\x07', '', clean)
                clean = clean.replace('\r', '')
                if not clean.strip():
                    continue
                if not clean.endswith("\n"):
                    clean += "\n"
                GLib.idle_add(self._parse_line, clean)
                if re.search(r'Track Download Done', clean, re.I):
                    self._track_done += 1
                    if self._total_tracks > 0:
                        GLib.idle_add(self.progress_bar.set_fraction,
                                      min(self._track_done / self._total_tracks, 1.0))
                        GLib.idle_add(self._set_status,
                                      f"💾  Saving files ({self._track_done}/{self._total_tracks})...", "info")
                    else:
                        GLib.idle_add(self._set_status, "💾  Saving files...", "info")
                m = re.search(r"([\d.]+\s*[KMG]B/s)", clean)
                if m:
                    GLib.idle_add(self.speed_lbl.set_markup,
                        f'<span foreground="#FF6B35" size="small">⬇  {m.group(1)}  </span>')
        except Exception:
            pass

        self._process.wait()
        GLib.idle_add(self._finish, self._process.returncode == 0)

    # ── Parsing log ──────────────────────────────────────────────────────────

    @staticmethod
    def _is_traceback_noise(line):
        """True for raw Python traceback frame lines (not the summary).

        Only the multi-line internal frames are noise; the final
        ``ExceptionType: message`` line is kept so it can still be mapped to
        user-friendly feedback.
        """
        s = line.rstrip("\n")
        if s.strip() == "Traceback (most recent call last):":
            return True
        if re.match(r'\s*File ".*", line \d+', s):
            return True
        if re.match(r'\s+[~^]+\s*$', s):
            return True
        return False

    def _parse_line(self, line):
        lo = line.lower()

        # Tally success/error signals before any log-noise suppression so a
        # collapsed traceback still counts toward the final outcome.
        self._track_streamrip_signals(line)

        # TIDAL token_expiry crash: streamrip raises ValueError on
        # float(token_expiry) when it is empty/corrupt. Scoped to a TIDAL
        # download exactly like the auth-error detection below.
        if (not self._tidal_auth_corrupted
                and tidal_auth.is_tidal_url(self._active_url)
                and tidal_auth.detect_tidal_token_expiry_error(line)):
            self._tidal_auth_corrupted = True
            friendly = ("🔐  TIDAL auth data is corrupted (empty/invalid "
                        "token_expiry) — open TIDAL Setup to repair.")
            self._set_status(friendly, "error")
            if not self._last_known_error:
                self._last_known_error = friendly
            self._auth_log(
                "🔐  streamrip raised a ValueError parsing token_expiry — "
                "the saved TIDAL session is corrupt/incomplete.\n", "error")

        if (not self._tidal_auth_required
                and tidal_auth.is_tidal_url(self._active_url)
                and tidal_auth.detect_tidal_auth_error(line)):
            self._tidal_auth_required = True
            self._set_status(
                "🔐  TIDAL authentication required — see the dialog.", "error")
            self._auth_log(
                "🔐  Detected a TIDAL re-authentication / resync prompt in "
                "streamrip output.\n", "error")

        # Deezer-specific classification, scoped to a Deezer download so a
        # Qobuz/TIDAL line never triggers it. The raw streamrip line is still
        # logged below (raw details preserved); this only adds a clear,
        # actionable one-liner. The provider-failure note is shown once so a
        # per-track flood collapses to a single explanation.
        if deezer.is_deezer_url(self._active_url):
            cat, friendly = deezer.classify_deezer_error(line)
            if cat == deezer.ERR_PROVIDER_FAILURE:
                if not self._deezer_provider_notified:
                    self._deezer_provider_notified = True
                    self._set_status(deezer.PROVIDER_FAILURE_MESSAGE, "error")
                    if not self._last_known_error:
                        self._last_known_error = deezer.PROVIDER_FAILURE_MESSAGE
                    self._log("⚠  " + deezer.PROVIDER_FAILURE_MESSAGE + "\n",
                              "error")
            elif cat and friendly:
                self._set_status(friendly, "error")
                if not self._last_known_error:
                    self._last_known_error = friendly

        # Collapse raw traceback frames unless auth-debug is enabled so a
        # streamrip crash does not flood the log with internal frames.
        if not tidal_auth.AUTH_DEBUG and self._is_traceback_noise(line):
            if not self._tb_noise_notified:
                self._tb_noise_notified = True
                self._log(
                    "ℹ️  Suppressed an internal traceback (run with "
                    "--debug-auth to show it).\n", "dim")
            return

        if any(w in lo for w in ["error", "failed", "exception", "traceback"]):
            tag = "error"
            friendly = parse_streamrip_error(line)
            if friendly:
                self._set_status(friendly, "error")
                if not self._last_known_error:
                    self._last_known_error = friendly
        elif any(w in lo for w in ["done", "complete", "finished", "success"]):
            tag = "ok"
            self.progress_bar.set_fraction(1.0)
        elif "downloading" in lo:
            tag = "track"
            clean = re.sub(r'\bINFO\b|\[.*?\]', '', line).strip()
            self._set_status(f"🎵  {clean[:80]}", "track")
        elif any(w in lo for w in ["grabbing", "starting", "fetching", "found",
                                    "album", "artist", "label", "release", "quality", "tracks:"]):
            tag = "info"
            if any(w in lo for w in ["fetching", "grabbing"]):
                self._set_status("⏳  Processing metadata...", "info")
        else:
            tag = None
        self._extract_meta_from_log(line)
        self._log(line, tag)

    def _extract_meta_from_log(self, line):
        # Log scraping only *fills* empty fields — it must never clobber the
        # richer values already pulled from the API, hence overwrite=False.
        def sm(key, value):
            self._set_meta(key, value, overwrite=False)

        m = re.search(r'^\s*Downloading\s+(.+?)\s*[─━—\-]{3,}\s*$', line)
        if m:
            title = m.group(1).strip()
            if title and not re.search(r'track|Track', title):
                sm("Album", title)

        m = re.search(r'(?:Downloading|Grabbing)\s+album[:\s]+(.+?)(?:\s*\[|$)', line, re.I)
        if m: sm("Album", m.group(1))

        m = re.search(r'Downloading track\s+[\'"]?(.+?)[\'"]?(?:\s+track\.py|\s*$)', line, re.I)
        if m: self._set_status(f"🎵  {m.group(1).strip()[:80]}", "track")

        m = re.search(r'\bArtist[:\s]+(.+)', line, re.I)
        if m: sm("Album Artist", m.group(1).split("  ")[0].split("\t")[0])

        m = re.search(r'\bQuality[:\s]+(.+)', line, re.I)
        if m: sm("Album Quality", m.group(1).split("  ")[0])

        m = re.search(r'\bTracks?[:\s]+(\d+)', line, re.I)
        if m:
            count = int(m.group(1))
            if self._total_tracks == 0:
                self._total_tracks = count
            sm("Total Tracks", str(count))

        m = re.search(r'Downloading track\s+[\'"]?(.+?)[\'"]?(?:\s+track\.py|\s*$)', line, re.I)
        if m:
            track_name = m.group(1).strip()
            self._set_status(f"🎵  {track_name[:80]}", "track")
            artist = self._get_meta_text("Album Artist")
            if artist != "—" and artist:
                threading.Thread(target=self._fetch_and_apply_lyrics, args=(artist, track_name), daemon=True).start()

        m = re.search(r'Release\s+date[:\s]+(\d{4}[-/]\d{2}[-/]\d{2})', line, re.I)
        if m: sm("Release Date", m.group(1))

        m = re.search(r'(?:UPC|Barcode)[:\s]+(\d{8,14})', line, re.I)
        if m: sm("UPC", m.group(1))

        if self._get_meta_text("Album Quality") in ("—", ""):
            for pat in [
                r'(FLAC\s+\d+\s*bit.{1,20}kHz)',
                r'(\d+\s*bit\s*/\s*[\d.]+\s*kHz)',
                r'(MP3\s+\d+\s*kbps?)',
                r'(Hi.?Res\s+FLAC)',
            ]:
                m = re.search(pat, line, re.I)
                if m: sm("Album Quality", m.group(1)); break

    # ── Fin ───────────────────────────────────────────────────────────────────

    def _reset_streamrip_signals(self):
        """Clear the per-download success/error tallies."""
        self._dl_error_count     = 0
        self._dl_skip_count      = 0
        self._dl_invalid_url     = False
        self._dl_finished_marker = False

    def _track_streamrip_signals(self, line):
        """Accumulate streamrip success/error signals from one output line.

        Runs before any log-noise suppression so a collapsed traceback is
        still counted toward the final outcome.
        """
        if streamrip_status.line_says_finished(line):
            self._dl_finished_marker = True
        if streamrip_status.line_is_invalid_url(line):
            self._dl_invalid_url = True
            return
        if streamrip_status.line_is_skip(line):
            self._dl_skip_count += 1
            return
        if streamrip_status.line_is_error(line):
            self._dl_error_count += 1

    def _compute_download_outcome(self, success):
        """Refine streamrip's exit code with the observed log signals."""
        return streamrip_status.classify_outcome(
            finished=self._dl_finished_marker,
            error_count=self._dl_error_count,
            skip_count=self._dl_skip_count,
            invalid_url=self._dl_invalid_url,
            process_ok=success,
        )

    def _streamrip_signal_summary(self):
        """Short '(N track error(s), M skipped)' suffix, or '' if clean."""
        parts = []
        if self._dl_error_count:
            parts.append(f"{self._dl_error_count} track "
                         f"error{'s' if self._dl_error_count != 1 else ''}")
        if self._dl_skip_count:
            parts.append(f"{self._dl_skip_count} skipped")
        return f" ({', '.join(parts)})" if parts else ""

    def _current_log_text(self):
        """Return the full plain text currently in the log buffer.

        Used by the error-summary builder and the Copy Log action so both
        see exactly what the user sees in the panel.
        """
        try:
            buf = self.log_view.get_buffer()
            return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        except Exception:
            return ""

    def _metadata_loaded(self):
        """True if the right-side sidebar shows at least one real value.

        Used by the error summary so users know whether the metadata /
        cover surface succeeded even though some tracks failed. Reads
        from the sidebar labels — never touches the protected widget
        layout, only inspects current text.
        """
        for key in self._meta:
            text = self._get_meta_text(key)
            if text and text not in ("—", ""):
                return True
        return False

    def _build_download_summary(self):
        """Compose the concise, multi-line summary shown above the log.

        Combines the streamrip-status tallies (counted as the download
        runs) with a pattern breakdown computed from the buffered log
        text. Returns ``""`` when the run was clean.
        """
        log_text = self._current_log_text()
        counts = log_format.count_error_patterns(log_text)
        return log_format.build_error_summary(
            counts,
            error_count=self._dl_error_count,
            skip_count=self._dl_skip_count,
            invalid_url=self._dl_invalid_url,
            metadata_loaded=self._metadata_loaded(),
        )

    def _log_error_summary(self):
        """Insert the concise error summary into the log, framed clearly.

        No-op when no errors were detected. The frame uses the existing
        ``dim`` tag for borders and ``error`` for the message body so the
        block stands out without redesigning the log panel.
        """
        summary = self._build_download_summary()
        if not summary:
            return
        border = "─" * 60 + "\n"
        self._log("\n" + border, "dim")
        self._log("⚠  Error summary\n", "error")
        self._log(summary + "\n", "error")
        self._log(border, "dim")

    def _copy_log_to_clipboard(self, *_):
        """Copy the full log buffer to the system clipboard.

        Mirrors the diagnostics dialog's Copy action so users can share
        the captured run output without re-opening Diagnostics.
        """
        text = self._current_log_text()
        if not text:
            self._set_status("ℹ  Log is empty — nothing to copy.", "info")
            return
        try:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(text, -1)
            clipboard.store()
            self._set_status("📋  Log copied to clipboard.", "ok")
        except Exception as exc:
            self._set_status(f"❌  Could not copy log: {exc}", "error")

    # ── Post-download library organisation ────────────────────────────────
    #
    # Reorganise streamrip's finished output into a predictable
    # NAS / Jellyfin / Symfonium library tree:
    #
    #   <Album Artist>/<Album Title>/<Quality>/NN. <Artist> - <Title>.<ext>
    #   Playlists/<Playlist Name>/NN. <Artist> - <Title>.<ext> + playlist.m3u
    #
    # This is pure post-processing: the streamrip download pipeline is never
    # touched, so Deezer/Qobuz downloads and the metadata sidebar are
    # unaffected. It runs ONLY after a successful or partial download (files
    # are no longer being written), preserves streamrip's track names, track
    # numbers, embedded tags and cover.jpg, never overwrites a different file,
    # and on ANY failure leaves every file exactly where streamrip wrote it.
    #
    # FLAC bit-depth / sample-rate per streamrip quality tier (2..4), used to
    # label the <Quality> folder for lossless downloads. Lossy formats get a
    # container-only label (MP3/AAC have no meaningful bit depth).
    _FLAC_QUALITY_SPECS = {2: (16, 44100), 3: (24, 96000), 4: (24, 192000)}

    def _organize_download(self, folder):
        """Reorganise *folder* into the library tree; return the recorded folder.

        *folder* is the directory streamrip created under the destination.
        Returns the (possibly new) top-level folder to show in history, or the
        original folder unchanged when organisation is disabled, not
        applicable, or failed. Files are never deleted on failure.
        """
        base = self._dest_folder
        if not folder or not os.path.isdir(folder):
            return folder
        # Only relocate a freshly-created subfolder; never reorganise the
        # destination root itself (that could sweep up unrelated files).
        if os.path.abspath(folder) == os.path.abspath(base):
            self._log(f"📂  Files saved to: {folder}\n", "info")
            return folder
        if not self._config.get("organize_library", True):
            self._log(f"📂  Files saved to: {folder}\n", "info")
            return folder
        try:
            if self._active_is_playlist:
                result = self._organize_playlist(base, folder)
            else:
                result = self._organize_album(base, folder)
        except Exception as exc:
            self._log(
                "⚠  Download finished, but library organization failed — "
                "files were left in the original output folder.\n", "error")
            self._log(f"    {folder}\n", "dim")
            self._log(f"    ({type(exc).__name__}: {exc})\n", "dim")
            return folder
        if not result:
            self._log(f"📂  Files saved to: {folder}\n", "info")
            return folder
        kind = "playlist" if self._active_is_playlist else "album"
        self._log(f"🗂  Organized {kind} into library:\n    {result}\n", "ok")
        return result

    def _organize_album(self, base, folder):
        meta = self._album_meta or {}
        artist = meta.get("artist", "")
        album = meta.get("album", "")
        # Without album metadata we cannot build a clean artist/album path;
        # leave the files where streamrip put them (no scary warning).
        if not artist and not album:
            return None
        files = self._collect_files(folder)
        if not files:
            return None
        names = [os.path.basename(p) for p in files]
        quality = self._quality_folder_label(names)
        moves = library.plan_album_layout(
            names,
            album_artist=artist or library.FALLBACK_ARTIST,
            album_title=album or library.FALLBACK_ALBUM,
            quality=quality,
        )
        abs_moves = [(src, os.path.join(base, *dst.split("/")))
                     for src, (_name, dst) in zip(files, moves)]
        self._execute_moves(abs_moves)
        self._cleanup_empty_dirs(folder, base)
        # Album-level folder (parent of the quality folder) for history.
        parts = moves[0][1].split("/")
        return os.path.join(base, *parts[:2])

    def _organize_playlist(self, base, folder):
        files = self._sort_playlist_files(self._collect_files(folder))
        if not files:
            return None
        names = [os.path.basename(p) for p in files]
        in_subfolder = self._config.get("playlists_subfolder", True)
        parent = library.PLAYLISTS_DIR if in_subfolder else ""
        plan = library.plan_playlist_layout(
            names,
            playlist_name=self._playlist_name(folder),
            service=qual.service_for_url(self._active_url) or None,
            playlist_id=self._playlist_id(),
            parent=parent,
        )
        abs_moves = [(src, os.path.join(base, *dst.split("/")))
                     for src, (_name, dst) in zip(files, plan["moves"])]
        self._execute_moves(abs_moves)
        dest_dir = os.path.join(base, *plan["folder"].split("/"))
        self._write_playlist_m3u(dest_dir, plan["audio"])
        self._cleanup_empty_dirs(folder, base)
        return dest_dir

    def _quality_folder_label(self, names):
        """Build the <Quality> folder label from the files actually written."""
        container = library.dominant_container(names) or "Audio"
        bit = rate = None
        if container == "FLAC":
            service = qual.service_for_url(self._active_url)
            clamped = (qual.clamp_quality(service, self._active_quality)
                       if service else self._active_quality)
            try:
                spec = self._FLAC_QUALITY_SPECS.get(int(clamped))
            except (TypeError, ValueError):
                spec = None
            if spec:
                bit, rate = spec
        return library.quality_folder(container, bit, rate)

    @staticmethod
    def _collect_files(folder):
        """All files under *folder* (recursive), as absolute paths."""
        collected = []
        for root, _dirs, names in os.walk(folder):
            for name in names:
                collected.append(os.path.join(root, name))
        return collected

    @staticmethod
    def _sort_playlist_files(files):
        """Order files by their leading track number so playlist order holds."""
        def key(path):
            name = os.path.basename(path)
            m = re.match(r'\s*(\d+)', name)
            if m:
                return (0, int(m.group(1)), name.lower())
            return (1, 0, name.lower())
        return sorted(files, key=key)

    def _playlist_name(self, folder):
        """Playlist name from streamrip's folder (it names it after the list)."""
        return os.path.basename(os.path.normpath(folder))

    def _playlist_id(self):
        m = re.search(r'/(?:playlist|sets)/([\w-]+)',
                      self._active_url or "", re.I)
        return m.group(1) if m else None

    def _execute_moves(self, abs_moves):
        """Move each ``(src, dst)``; never overwrite a different file."""
        for src, dst in abs_moves:
            if os.path.abspath(src) == os.path.abspath(dst):
                continue
            if not os.path.exists(src):
                continue
            dst_dir = os.path.dirname(dst)
            os.makedirs(dst_dir, exist_ok=True)
            final = dst
            if os.path.exists(final):
                # Same content (e.g. a re-download) → keep the existing file.
                try:
                    if os.path.getsize(final) == os.path.getsize(src):
                        os.remove(src)
                        continue
                except OSError:
                    pass
                # Different content → never overwrite; pick a unique name.
                try:
                    existing = set(os.listdir(dst_dir))
                except OSError:
                    existing = set()
                final = os.path.join(
                    dst_dir,
                    library.dedupe_filename(os.path.basename(dst), existing))
            shutil.move(src, final)

    def _write_playlist_m3u(self, dest_dir, audio_names):
        """Write playlist.m3u listing *audio_names* in order (best-effort)."""
        if not audio_names:
            return
        try:
            body = library.m3u_content(audio_names)
            path = os.path.join(dest_dir, library.PLAYLIST_FILE)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.replace(tmp, path)
        except OSError as exc:
            self._log(f"⚠  Could not write {library.PLAYLIST_FILE}: {exc}\n",
                      "error")

    @staticmethod
    def _cleanup_empty_dirs(folder, base):
        """Remove directories emptied by the move, never the destination root."""
        base_abs = os.path.abspath(base)
        for root, _dirs, _files in os.walk(folder, topdown=False):
            if os.path.abspath(root) == base_abs:
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
            except OSError:
                pass

    def _finish_full_success(self):
        self._set_status("✅  Download complete!", "ok")
        self.progress_bar.set_fraction(1.0)
        self._log("\n✅  All downloads finished!\n", "ok")
        folder = self._detect_new_folder(self._dest_folder, self._dest_dirs_snapshot) or self._dest_folder
        folder = self._organize_download(folder)
        self._history_set_status(self._current_history_entry, "Completed", folder=folder)
        self._queue_set_status(self._current_queue_item, "Completed")

    def _finish_with_warnings(self):
        self.progress_bar.set_fraction(1.0)
        self._set_status(
            "⚠  Download finished with errors — check the log.", "error")
        self._log(
            "\n⚠  Download finished with errors — check the log."
            f"{self._streamrip_signal_summary()}\n", "error")
        self._log_error_summary()
        # Some tracks may still have landed; keep the folder link if one
        # was created so partial results stay reachable.
        folder = self._detect_new_folder(self._dest_folder, self._dest_dirs_snapshot)
        if folder:
            folder = self._organize_download(folder)
        self._history_set_status(self._current_history_entry, "Warning", folder=folder)
        self._queue_set_status(self._current_queue_item, "Warning")

    def _finish_invalid_url(self):
        self._set_status(
            "❌  streamrip rejected the URL — see the log.", "error")
        self._log("\n❌  streamrip could not use this URL.\n", "error")
        self._log(
            "💡  Try opening the link in your browser and paste the "
            "final service URL.\n", "info")
        self._log_error_summary()
        self._history_set_status(self._current_history_entry, "Failed")
        self._queue_set_status(self._current_queue_item, "Failed")

    def _finish_failed(self):
        code = self._process.returncode if self._process else -1
        if code != -15:
            status_msg = self._last_known_error or "❌  Download failed — check the log."
            self._set_status(status_msg, "error")
            self._log("\n❌  Download failed.\n", "error")
        self._history_set_status(self._current_history_entry, "Failed")
        self._queue_set_status(self._current_queue_item, "Failed")

    def _finish(self, success):
        user_stopped = (self._process is not None
                        and self._process.returncode == -15)
        if user_stopped:
            self._finish_failed()
        else:
            outcome = self._compute_download_outcome(success)
            if outcome == streamrip_status.SUCCESS:
                self._finish_full_success()
            elif outcome == streamrip_status.PARTIAL:
                self._finish_with_warnings()
            elif outcome == streamrip_status.INVALID_URL:
                self._finish_invalid_url()
            else:
                self._finish_failed()

        self._post_download_config_audit()
        tidal_corrupted = (
            not success and self._tidal_auth_corrupted and not user_stopped)
        tidal_blocked = (
            not success
            and self._tidal_auth_required
            and not tidal_corrupted
            and not user_stopped
        )

        self._current_history_entry = None
        self._current_queue_item    = None
        self.btn_download.set_sensitive(True)
        self.btn_stop.hide()
        self.speed_lbl.set_markup("")
        if tidal_corrupted:
            GLib.idle_add(self._show_tidal_auth_corrupted_dialog)
            self._queue_stopped_by_user = False
        elif tidal_blocked:
            GLib.idle_add(self._show_tidal_auth_expired_dialog)
            self._queue_stopped_by_user = False
        elif self._queue_stopped_by_user:
            self._queue_stopped_by_user = False
        else:
            self._queue_start_next()

    def _post_download_config_audit(self):
        """Log whether streamrip rewrote config.toml during the download.

        This makes the streamrip-side token-persistence behaviour visible:
        on first login streamrip flushes the new tokens (file changes); on
        later runs it refreshes the token only in memory and the file is
        unchanged — which is exactly why a stale token keeps prompting.
        """
        pre = self._cfg_fingerprint_pre
        self._cfg_fingerprint_pre = None
        if not pre or not pre[0]:
            return
        cfg = self._streamrip_config_path()
        post = tidal_auth.config_fingerprint(cfg)
        if not post[0]:
            self._auth_log(
                "⚠  config.toml is missing after the download — streamrip "
                "may have failed to persist auth.\n", "error")
            return
        if post[3] != pre[3]:
            self._auth_log(
                "🗂  streamrip rewrote config.toml during this run "
                "(tokens were persisted).\n", "ok")
        else:
            self._auth_log(
                "🗂  config.toml unchanged after this run — streamrip did "
                "not re-persist TIDAL tokens (expected on token reuse).\n",
                "info")

    def _log(self, text, tag=None):
        # Sanitise + soft-wrap before inserting so stray control bytes,
        # mojibake or unbroken URLs never make the panel unreadable. The
        # original payload is preserved (paths, errors stay copy-able);
        # this is purely a display-side cleanup.
        display = log_format.prepare_for_display(text)
        if not display:
            return
        buf = self.log_view.get_buffer()
        end = buf.get_end_iter()
        if tag:
            buf.insert_with_tags_by_name(end, display, tag)
        else:
            buf.insert(end, display)
        adj = self._scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def _clear_log(self):
        self.log_view.get_buffer().set_text("")

    def _set_status(self, text, style="info"):
        self.status_lbl.set_markup(build_status_markup(text, style))

    def _reset_meta(self):
        # Tolerate any missing/renamed label so a UI refactor degrades the
        # sidebar gracefully instead of crashing the whole reset path.
        for lbl in self._meta.values():
            if lbl is None:
                continue
            try:
                lbl.set_markup('<span foreground="#333333" size="small">—</span>')
            except Exception:
                pass
        self._set_lyrics('<span foreground="#333333" size="small">—</span>')
        self._set_placeholder_cover()
        self._set_cover_placeholder_label()
        if self.speed_lbl is not None:
            self.speed_lbl.set_markup("")

    def _set_placeholder_cover(self):
        """Show the neutral placeholder tile (startup, reset, cover failure)."""
        if self.cover_img is None:
            return
        try:
            pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 185, 185)
            pb.fill(0x161616ff)
            self.cover_img.set_from_pixbuf(pb)
        except Exception:
            pass

    def _set_cover_placeholder_label(self):
        """Restore the dim 'COVER' caption used when no art is shown."""
        if self.cover_lbl is None:
            return
        try:
            self.cover_lbl.set_markup(
                '<span foreground="#555555" size="small" letter_spacing="200">COVER</span>')
        except Exception:
            pass

    def _streamrip_config_path(self):
        # Mirrors streamrip's own click.get_app_dir("streamrip") resolution
        # (Linux: ~/.config/streamrip, Windows: %APPDATA%/streamrip).
        return tidal_auth.streamrip_config_path()

    def _scrub_secrets(self, text):
        """Redact anything token/credential shaped before it is shown anywhere.

        Delegates to the isolated, dependency-free helper so the masking
        rules live in one place and can be unit-tested without GTK.
        """
        return tidal_auth.scrub_secrets(text)

    def _auth_log(self, message, tag="info"):
        """Log an auth-diagnostic line (always scrubbed) from any thread."""
        GLib.idle_add(self._log, tidal_auth.scrub_secrets(message), tag)

    def _log_tidal_preflight(self, cfg_path):
        """Log presence-only TIDAL auth state before a TIDAL download.

        Never logs a token value — only whether tokens are present and
        whether the saved session looks usable, so a failed download can be
        traced to auth without leaking secrets.
        """
        st = tidal_auth.tidal_auth_status(cfg_path)
        access = "present" if st["access_present"] else "MISSING"
        refresh = "present" if st["refresh_present"] else "MISSING"
        self._auth_log(
            f"🔐  TIDAL auth check — access_token: {access}, "
            f"refresh_token: {refresh} (values hidden).\n", "info")
        if st["looks_authenticated"]:
            self._auth_log(
                "🔐  TIDAL session looks valid; reusing saved tokens.\n",
                "ok")
        else:
            for problem in st["problems"]:
                self._auth_log(f"⚠  TIDAL: {problem}\n", "error")

    def _tidal_connection_summary(self, cfg_path):
        """Lightweight, offline TIDAL connection check → (message, kind).

        Inspects only the saved config (no network, no download) and reports
        whether the session looks reusable, including expiry, never showing
        a token value.
        """
        if not os.path.exists(cfg_path):
            return ("streamrip config.toml not found — run TIDAL Setup or "
                    "`rip config reset` first.", "warn")
        st = tidal_auth.tidal_auth_status(cfg_path)
        a = "present" if st["access_present"] else "missing"
        r = "present" if st["refresh_present"] else "missing"
        base = f"access_token: {a}, refresh_token: {r} (values hidden)."
        if st["looks_authenticated"]:
            extra = ""
            if st["near_expiry"]:
                extra = (" Token is close to expiry — streamrip will refresh "
                         "it on the next download.")
            return (f"TIDAL session looks valid — {base}{extra}", "ok")
        if st["problems"]:
            return (f"TIDAL not ready — {base} " + " ".join(st["problems"]),
                    "warn")
        return (f"TIDAL not logged in yet — {base}", "info")

    def _read_streamrip_section(self, cfg_path, section):
        """Best-effort read of one [section] table from config.toml.

        Returns a dict of string values, or {} on any problem. Never raises and
        never logs the values it reads.
        """
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return {}
        try:
            import tomllib  # stdlib on Python 3.11+
            sec = tomllib.loads(text).get(section)
            if isinstance(sec, dict):
                return {k: ("" if v is None else str(v)) for k, v in sec.items()}
        except Exception:
            pass
        result = {}
        in_section = False
        for line in text.split("\n"):
            s = line.strip()
            m = re.match(r"\[([^\]]+)\]\s*$", s)
            if m:
                in_section = m.group(1).strip() == section
                continue
            if in_section:
                km = re.match(r'([A-Za-z0-9_]+)\s*=\s*"?(.*?)"?\s*$', s)
                if km:
                    result[km.group(1)] = km.group(2)
        return result

    def _write_streamrip_section(self, cfg_path, section, updates, aliases):
        """Update key = "value" lines inside an existing [section] only.

        ``updates`` maps a canonical key to its new value; ``aliases`` maps the
        same canonical key to the list of accepted key names (in priority
        order) so this works across streamrip config schema versions. Every
        other section, comment and blank line is preserved verbatim. The file
        is rewritten atomically with 0600 permissions because it now holds a
        password. Returns (ok, error_message); error messages never contain
        credential values.
        """
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                lines = f.read().split("\n")
        except OSError as exc:
            return False, f"Could not read config.toml ({exc.strerror or 'I/O error'})."

        start = None
        for i, ln in enumerate(lines):
            m = re.match(r"\s*\[([^\]]+)\]\s*$", ln)
            if m and m.group(1).strip() == section:
                start = i
                break
        if start is None:
            return False, f"Section [{section}] is missing from config.toml."

        end = len(lines)
        for j in range(start + 1, len(lines)):
            if re.match(r"\s*\[([^\]]+)\]\s*$", lines[j]):
                end = j
                break

        for canon, value in updates.items():
            accepted = aliases.get(canon, [canon])
            written = False
            for k in range(start + 1, end):
                km = re.match(r"\s*([A-Za-z0-9_]+)\s*=", lines[k])
                if km and km.group(1) in accepted:
                    lines[k] = f'{km.group(1)} = "{toml_escape(value)}"'
                    written = True
                    break
            if not written:
                lines.insert(start + 1, f'{accepted[0]} = "{toml_escape(value)}"')
                end += 1

        tmp_path = cfg_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, cfg_path)
        except OSError as exc:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False, f"Could not write config.toml ({exc.strerror or 'I/O error'})."
        return True, None

    def _finish_tidal_corrupted(self):
        """UI reset + warning for the pre-download corrupt-auth abort.

        Used when the saved TIDAL session is detectably broken (empty/invalid
        token_expiry with an access_token present) so we never even spawn
        streamrip into its ValueError crash loop. Mirrors the failure branch
        of ``_finish`` but without any process handling, and never advances
        the queue (the user must re-authenticate first).
        """
        self._set_status(
            "🔐  TIDAL auth data is corrupted — open TIDAL Setup to repair.",
            "error")
        self._log(
            "\n🔐  TIDAL download skipped: saved auth is corrupt/incomplete.\n",
            "error")
        self._history_set_status(self._current_history_entry, "Failed")
        self._queue_set_status(self._current_queue_item, "Failed")
        self._current_history_entry = None
        self._current_queue_item = None
        self.btn_download.set_sensitive(True)
        self.btn_stop.hide()
        self.speed_lbl.set_markup("")
        self._queue_stopped_by_user = False
        GLib.idle_add(self._show_tidal_auth_corrupted_dialog)
        return False

    def _auto_repair_tidal_auth(self, then_relogin=True):
        """Optional repair: clear only the broken TIDAL auth fields.

        Removes the corrupt/incomplete TIDAL token fields from streamrip's
        config.toml (preserving every other setting), then optionally reopens
        the assisted login so a clean, complete token set is written. Never
        logs or shows a token value — ``clear_broken_tidal_auth`` returns
        only field names.
        """
        cfg = self._streamrip_config_path()
        ok, err, cleared = tidal_auth.clear_broken_tidal_auth(cfg)
        if ok and cleared:
            self._auth_log(
                "🛠  Repaired TIDAL auth — reset corrupt fields ["
                + ", ".join(cleared) + "] in config.toml; all other "
                "settings were preserved.\n", "ok")
            self._set_status(
                "🛠  TIDAL auth reset — please log in again.", "info")
        elif ok:
            self._auth_log(
                "🛠  TIDAL auth was already clean — no fields needed "
                "resetting.\n", "info")
        else:
            self._auth_log(
                f"⚠  Could not repair TIDAL auth: {err}\n", "error")
            self._set_status(
                "⚠  Automatic TIDAL repair failed — see the log.", "error")
        if then_relogin:
            GLib.idle_add(self._show_tidal_setup_dialog)
        return False

    def _show_tidal_auth_corrupted_dialog(self):
        """Clear warning for corrupt/incomplete TIDAL auth + one-click fix.

        Shown when token_expiry is empty/invalid (or another auth field is
        unusable) — the state that crashes streamrip and triggers the
        re-login loop. Explains the problem in plain language, shows only a
        secret-free diagnostic, and offers an optional automatic repair plus
        one-click re-authentication. No token value is ever displayed.
        """
        cfg = self._streamrip_config_path()
        s = tidal_auth.sanitize_tidal_auth_state(cfg)

        detail = (
            "Auryn found a TIDAL login on disk, but the saved authentication "
            "data is incomplete or corrupted.\n\n"
            + s["summary"] + "\n\n"
            "This is not a bad link or a wrong password — streamrip wrote a "
            "partial token set (a common cause: an empty token_expiry), so "
            "loading the saved session fails and every download keeps asking "
            "you to log in again.\n\n"
            "Auryn can repair this for you: it removes only the broken TIDAL "
            "auth fields from streamrip's config (every other setting is kept "
            "untouched) and then reopens the assisted login so a fresh, "
            "complete token set is written. Your TIDAL password is never "
            "seen or stored by Auryn."
        )
        fields = s["fields"]
        detail += (
            "\n\nAuth fields (values hidden):"
            f"\n  • access_token  : {fields['access_token']}"
            f"\n  • refresh_token : {fields['refresh_token']}"
            f"\n  • user_id       : {fields['user_id']}"
            f"\n  • token_expiry  : {fields['token_expiry']}"
            f"\n  • refresh possible : {s['refresh_possible']}"
        )

        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="TIDAL authentication data is corrupted",
        )
        dlg.format_secondary_text(detail)
        later_btn = dlg.add_button("Later", Gtk.ResponseType.CLOSE)
        relogin_btn = dlg.add_button("Re-login only", 2)
        repair_btn = dlg.add_button("Repair & re-login", 1)
        for _b in (later_btn, relogin_btn, repair_btn):
            _b.get_style_context().add_class("neutral-btn")
        repair_btn.set_sensitive(bool(s["can_repair"]))
        dlg.set_default_response(1 if s["can_repair"] else 2)
        response = dlg.run()
        dlg.destroy()
        if response == 1:
            GLib.idle_add(self._auto_repair_tidal_auth, True)
        elif response == 2:
            GLib.idle_add(self._show_tidal_setup_dialog)
        return False

    def _show_tidal_auth_expired_dialog(self):
        """Explain a TIDAL auth/resync failure and offer to re-run setup.

        Shown when a TIDAL download fails because streamrip asked to log in
        again. The wording makes clear this is a token-persistence problem,
        not a bad URL, and never displays any token value.
        """
        cfg = self._streamrip_config_path()
        st = tidal_auth.tidal_auth_status(cfg)
        detail = (
            "Your TIDAL download stopped because streamrip asked to log in "
            "again.\n\n"
            "TIDAL access tokens expire about once a week. streamrip refreshes "
            "them in memory but does not always write the refreshed token back "
            "to its config file, so a previously working login can start "
            "prompting again.\n\n"
            "Re-running TIDAL Setup writes a fresh, complete token set and "
            "fixes this. Your TIDAL password is never seen or stored by "
            "Auryn."
        )
        if st["problems"]:
            detail += "\n\nDiagnostics:\n" + "\n".join(
                f"  • {p}" for p in st["problems"])

        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="TIDAL authentication expired",
        )
        dlg.format_secondary_text(detail)
        later_btn = dlg.add_button("Later", Gtk.ResponseType.CLOSE)
        setup_btn = dlg.add_button("Reopen TIDAL Setup", Gtk.ResponseType.OK)
        later_btn.get_style_context().add_class("neutral-btn")
        setup_btn.get_style_context().add_class("neutral-btn")
        dlg.set_default_response(Gtk.ResponseType.OK)
        response = dlg.run()
        dlg.destroy()
        if response == Gtk.ResponseType.OK:
            GLib.idle_add(self._show_tidal_setup_dialog)
        return False

    def _show_tidal_setup_dialog(self, *_):
        """Assisted TIDAL login.

        TIDAL has no email/password in streamrip — it uses a web/device
        login. This dialog runs streamrip, surfaces the login URL it prints
        (with a button to open it in a browser), streams its sanitized
        output, and detects success by watching for access/refresh tokens in
        streamrip's own config.toml. No password is ever requested and no
        token value is ever shown or logged.
        """
        cfg_path = self._streamrip_config_path()

        dlg = Gtk.Dialog(
            title="TIDAL Setup",
            transient_for=self.window,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        dlg.set_default_size(560, 520)
        close_btn = dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        close_btn.get_style_context().add_class("neutral-btn")

        content = dlg.get_content_area()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_start(20)
        outer.set_margin_end(20)
        outer.set_margin_top(16)
        outer.set_margin_bottom(16)
        content.pack_start(outer, True, True, 0)

        def note(markup_text):
            lbl = Gtk.Label()
            lbl.set_markup(markup_text)
            lbl.set_halign(Gtk.Align.START)
            lbl.set_line_wrap(True)
            lbl.set_xalign(0.0)
            return lbl

        outer.pack_start(note(
            '<span foreground="#e8e8e8" weight="bold">TIDAL login</span>'
        ), False, False, 0)
        outer.pack_start(note(
            '<span foreground="#888888" size="small">'
            '<b>Why no email/password?</b> TIDAL’s API only offers an '
            'OAuth 2.0 <b>device authorization</b> sign-in (the “approve '
            'this device” browser step). It exposes no password-grant '
            'endpoint, so streamrip — and therefore Auryn — cannot '
            'accept a TIDAL email/password the way Qobuz can. This is a TIDAL '
            'platform limitation, not an Auryn restriction.\n\n'
            'Instead TIDAL uses a <b>web/device login</b>: streamrip prints a '
            'link, you open it in your browser and approve this device. '
            'streamrip then stores and refreshes the access/refresh tokens in '
            'its own config.toml — Auryn never sees or stores a TIDAL '
            'password.</span>'
        ), False, False, 0)

        safe_cfg = (cfg_path.replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))
        outer.pack_start(note(
            '<span foreground="#666666" size="small">streamrip config:\n'
            f'<tt>{safe_cfg}</tt></span>'
        ), False, False, 0)

        status_lbl = Gtk.Label()
        status_lbl.set_halign(Gtk.Align.START)
        status_lbl.set_line_wrap(True)
        status_lbl.set_xalign(0.0)
        outer.pack_start(status_lbl, False, False, 0)

        url_lbl = Gtk.Label()
        url_lbl.set_halign(Gtk.Align.START)
        url_lbl.set_line_wrap(True)
        url_lbl.set_xalign(0.0)
        url_lbl.set_selectable(True)
        outer.pack_start(url_lbl, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        start_btn = Gtk.Button(label="Start TIDAL login")
        open_btn = Gtk.Button(label="Open login URL")
        test_btn = Gtk.Button(label="Test TIDAL login")
        repair_btn = Gtk.Button(label="Repair TIDAL session")
        for _b in (start_btn, open_btn, test_btn, repair_btn):
            _b.get_style_context().add_class("neutral-btn")
        open_btn.set_sensitive(False)
        btn_row.pack_start(start_btn, False, False, 0)
        btn_row.pack_start(open_btn, False, False, 0)
        btn_row.pack_start(test_btn, False, False, 0)
        btn_row.pack_start(repair_btn, False, False, 0)
        outer.pack_start(btn_row, False, False, 0)

        out_view = Gtk.TextView()
        out_view.set_editable(False)
        out_view.set_cursor_visible(False)
        out_view.set_monospace(True)
        out_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        out_scroll = Gtk.ScrolledWindow()
        out_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        out_scroll.set_hexpand(True)
        out_scroll.set_vexpand(True)
        out_scroll.add(out_view)
        out_scroll.get_style_context().add_class("history-row")
        outer.pack_start(out_scroll, True, True, 0)

        stop = threading.Event()
        state = {"proc": None, "url": None, "running": False}
        colors = {"info": "#888888", "ok": "#4CAF50",
                  "warn": "#FFB300", "error": "#e74c3c"}

        def set_status(msg, kind="info"):
            safe = (msg.replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))
            status_lbl.set_markup(
                f'<span foreground="{colors.get(kind, "#888888")}" '
                f'size="small">{safe}</span>')
            return False

        def append_output(text):
            buf = out_view.get_buffer()
            buf.insert(buf.get_end_iter(), text)
            adj = out_scroll.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False

        def refresh_token_status():
            msg, kind = self._tidal_connection_summary(cfg_path)
            set_status(msg, kind)
            return False

        def show_config_reset():
            for ch in btn_row.get_children():
                ch.set_sensitive(False)
            fix_btn = Gtk.Button(label="Run  rip config reset")
            fix_btn.get_style_context().add_class("neutral-btn")
            fix_btn.set_halign(Gtk.Align.START)

            def on_fix(_b):
                rip = self._streamrip_cmd()
                if not rip:
                    set_status("rip was not found. Install streamrip, then "
                               "run `rip config reset` in a terminal.", "error")
                    return
                try:
                    subprocess.run(rip + ["config", "reset"],
                                   capture_output=True, text=True, timeout=30)
                except Exception:
                    pass
                if os.path.exists(cfg_path):
                    fix_btn.destroy()
                    for ch in btn_row.get_children():
                        ch.set_sensitive(True)
                    open_btn.set_sensitive(False)
                    refresh_token_status()
                else:
                    set_status("Could not create config.toml automatically. "
                               "Run `rip config reset` in a terminal, then "
                               "reopen this dialog.", "error")

            fix_btn.connect("clicked", on_fix)
            outer.pack_start(fix_btn, False, False, 0)
            outer.show_all()

        def on_url_found(url):
            state["url"] = url
            open_btn.set_sensitive(True)
            safe = (url.replace("&", "&amp;")
                    .replace("<", "&lt;").replace(">", "&gt;"))
            url_lbl.set_markup(
                '<span foreground="#FF6B35" size="small">Login link: '
                f'<tt>{safe}</tt></span>')
            set_status("Open the login link in your browser and approve this "
                       "device. Waiting for streamrip to receive the "
                       "tokens…", "info")
            return False

        def finish_worker(outcome):
            state["running"] = False
            start_btn.set_sensitive(True)
            test_btn.set_sensitive(True)
            repair_btn.set_sensitive(True)
            kind = outcome.get("state")
            if kind == "ok":
                set_status(
                    "TIDAL login complete — access and refresh tokens were "
                    "written and validated (values hidden). The saved "
                    "session will be reused for downloads.", "ok")
                GLib.idle_add(
                    self._log,
                    "🔐  TIDAL login completed — full token set persisted by "
                    "streamrip and validated.\n", "ok")
            elif kind == "partial":
                problems = outcome.get("problems") or []
                msg = ("TIDAL login is incomplete — streamrip did not "
                       "persist a full, valid token set, so downloads will "
                       "keep asking you to log in.")
                if problems:
                    msg += "  " + "  ".join(problems)
                msg += "  Try 'Start TIDAL login' again."
                set_status(msg, "warn")
                self._auth_log(
                    "⚠  TIDAL setup produced an incomplete token set — "
                    "asking the user to retry.\n", "error")
            elif kind == "timeout":
                set_status("Timed out waiting for TIDAL login. Open the link "
                           "and approve the device, then try again.", "warn")
            elif kind == "error":
                set_status(outcome.get("message")
                           or "TIDAL login could not start.", "error")
            elif not stop.is_set():
                set_status("TIDAL login did not complete. Check the output "
                           "above and try again.", "warn")
            return False

        def worker():
            rip = self._streamrip_cmd()
            if not rip:
                GLib.idle_add(finish_worker, {
                    "state": "error",
                    "message": "rip (streamrip) was not found in PATH. "
                               "Install streamrip first."})
                return

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            # Same Windows cp1252 issue as the download path: force UTF-8 mode
            # in the child so streamrip can print Unicode without crashing.
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                             if IS_WINDOWS else 0)
            try:
                proc = subprocess.Popen(
                    rip + ["url", TIDAL_LOGIN_PROBE_URL],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, bufsize=1,
                    encoding="utf-8", errors="replace",
                    env=env, creationflags=creationflags,
                )
            except Exception as exc:
                GLib.idle_add(finish_worker, {
                    "state": "error",
                    "message": f"Could not start rip: {exc}"})
                return
            state["proc"] = proc

            def reader():
                try:
                    for raw in proc.stdout:
                        if stop.is_set():
                            break
                        clean = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', raw)
                        clean = re.sub(r'\x1b\][^\x07]*\x07', '', clean)
                        clean = clean.replace('\r', '')
                        clean = self._scrub_secrets(clean)
                        if not clean.strip():
                            continue
                        if not clean.endswith("\n"):
                            clean += "\n"
                        GLib.idle_add(append_output, clean)
                        if not state["url"]:
                            m = TIDAL_LOGIN_URL_RE.search(clean)
                            if m:
                                GLib.idle_add(on_url_found,
                                              m.group(0).rstrip('.,);]'))
                except Exception:
                    pass

            threading.Thread(target=reader, daemon=True).start()

            # Phase 1: wait for streamrip to write a token, or for it to
            # exit / time out. We must NOT kill streamrip the instant a
            # token byte appears: streamrip only flushes the *complete*
            # token set (user_id, country_code, access, refresh,
            # token_expiry) when its own config context manager exits.
            # Terminating mid-flush is exactly what leaves a partial
            # config.toml and causes the next download to re-authenticate.
            start_ts = time.time()
            tokens_seen_ts = None
            timed_out = False
            while True:
                if stop.is_set():
                    break
                if proc.poll() is not None:
                    break
                if tokens_seen_ts is None and tidal_auth.tidal_auth_present(
                        cfg_path):
                    tokens_seen_ts = time.time()
                    GLib.idle_add(
                        set_status,
                        "Tokens received — waiting for streamrip to finish "
                        "writing them…", "info")
                if tokens_seen_ts is not None:
                    # streamrip exits on its own once the throwaway probe
                    # URL fails; give it a bounded grace period to do so.
                    if time.time() - tokens_seen_ts > 45:
                        break
                elif time.time() - start_ts > 240:
                    timed_out = True
                    break
                time.sleep(0.5)

            # Let streamrip exit cleanly so its config flush completes;
            # only force it down if it overruns the grace window.
            try:
                if proc.poll() is None:
                    if not stop.is_set():
                        try:
                            proc.wait(timeout=20)
                        except Exception:
                            pass
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except Exception:
                            proc.kill()
            except Exception:
                pass

            # Settle so we never validate a config.toml mid-write, then
            # check the *integrity* of what streamrip persisted.
            if not stop.is_set():
                time.sleep(1.2)
            st = tidal_auth.tidal_auth_status(cfg_path)
            if st["looks_authenticated"]:
                outcome = {"state": "ok"}
            elif st["access_present"] or st["refresh_present"]:
                outcome = {"state": "partial", "problems": st["problems"]}
            elif timed_out:
                outcome = {"state": "timeout"}
            else:
                outcome = {"state": "none"}

            if tidal_auth.AUTH_DEBUG:
                for ln in tidal_auth.auth_debug_report(cfg_path).split("\n"):
                    self._auth_log(ln + "\n", "dim")

            GLib.idle_add(finish_worker, outcome)

        def on_start(_b):
            if state["running"]:
                return
            if not os.path.exists(cfg_path):
                set_status("streamrip config.toml not found — create it "
                           "first.", "error")
                return
            if not self._find_rip_path():
                set_status("rip (streamrip) was not found in PATH. Install "
                           "streamrip first.", "error")
                return
            stop.clear()
            state["url"] = None
            state["running"] = True
            open_btn.set_sensitive(False)
            start_btn.set_sensitive(False)
            test_btn.set_sensitive(False)
            repair_btn.set_sensitive(False)
            url_lbl.set_markup("")
            out_view.get_buffer().set_text("")
            set_status("Starting streamrip… a TIDAL login link should appear "
                       "below shortly.", "info")
            threading.Thread(target=worker, daemon=True).start()

        def on_open(_b):
            if state["url"]:
                try:
                    webbrowser.open(state["url"])
                except Exception as exc:
                    set_status(f"Could not open browser: {exc}", "error")

        def on_test(_b):
            if not self._find_rip_path():
                set_status("rip (streamrip) was not found in PATH. Install "
                           "streamrip first.", "error")
                return
            if not os.path.exists(cfg_path):
                set_status("streamrip config.toml not found — create it "
                           "first.", "warn")
                return
            refresh_token_status()

        def on_repair(_b):
            if state["running"]:
                return
            if not os.path.exists(cfg_path):
                set_status("streamrip config.toml not found — nothing to "
                           "repair. Create it first.", "warn")
                return
            ok, err, cleared = tidal_auth.clear_broken_tidal_auth(
                cfg_path, force=True)
            if ok:
                GLib.idle_add(
                    self._auth_log,
                    "🛠  TIDAL session reset — cleared ["
                    + (", ".join(cleared) if cleared else "no fields")
                    + "] in config.toml; every other setting was "
                    "preserved.\n", "ok")
                state["url"] = None
                open_btn.set_sensitive(False)
                url_lbl.set_markup("")
                set_status(
                    "TIDAL session reset (all other settings preserved). "
                    "Click 'Start TIDAL login' to sign in again.", "ok")
            else:
                set_status(err or "Could not repair the TIDAL session.",
                           "error")

        start_btn.connect("clicked", on_start)
        open_btn.connect("clicked", on_open)
        test_btn.connect("clicked", on_test)
        repair_btn.connect("clicked", on_repair)

        if not os.path.exists(cfg_path):
            set_status(
                "streamrip config.toml was not found. Create it before "
                "logging in.", "warn")
            show_config_reset()
        else:
            refresh_token_status()

        dlg.show_all()

        def on_response(_d, _r):
            stop.set()
            p = state.get("proc")
            if p is not None and p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass

        dlg.connect("response", on_response)
        dlg.run()
        stop.set()
        p = state.get("proc")
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
        dlg.destroy()
        return False

    def _show_credentials_dialog(self, *_):
        RESP_TEST = 10

        dlg = Gtk.Dialog(
            title="Service Credentials",
            transient_for=self.window,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        dlg.set_default_size(470, -1)

        test_btn   = dlg.add_button("Test credentials", RESP_TEST)
        cancel_btn = dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save_btn   = dlg.add_button("Save",   Gtk.ResponseType.OK)
        for _b in (test_btn, cancel_btn, save_btn):
            _b.get_style_context().add_class("neutral-btn")

        content = dlg.get_content_area()
        content.set_spacing(0)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_start(20)
        outer.set_margin_end(20)
        outer.set_margin_top(16)
        outer.set_margin_bottom(16)

        intro = Gtk.Label()
        intro.set_markup(
            '<span foreground="#888888" size="small">'
            'Credentials are written only to the streamrip config file. '
            'Auryn never stores them.</span>'
        )
        intro.set_halign(Gtk.Align.START)
        intro.set_line_wrap(True)
        intro.set_xalign(0.0)
        outer.pack_start(intro, False, False, 0)

        sel_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        sel_lbl = Gtk.Label()
        sel_lbl.set_markup('<span foreground="#888888" size="small">Service</span>')
        combo = Gtk.ComboBoxText()
        # Deezer first and flagged as recommended (large catalog, simplest setup
        # — a single ARL token). Qobuz/TIDAL remain fully available.
        for sid, label in (("deezer", deezer.RECOMMENDED_LABEL),
                           ("qobuz", "Qobuz"), ("tidal", "TIDAL")):
            combo.append(sid, label)
        combo.set_active(0)
        sel_row.pack_start(sel_lbl, False, False, 0)
        sel_row.pack_start(combo, True, True, 0)
        outer.pack_start(sel_row, False, False, 0)

        outer.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0
        )

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.pack_start(body, True, True, 0)

        status_lbl = Gtk.Label()
        status_lbl.set_halign(Gtk.Align.START)
        status_lbl.set_line_wrap(True)
        status_lbl.set_xalign(0.0)
        outer.pack_start(status_lbl, False, False, 0)

        content.pack_start(outer, True, True, 0)

        state = {"service": "qobuz", "entries": {}, "config_ok": False}

        def set_status(msg, kind="info"):
            colors = {"info": "#888888", "ok": "#4CAF50",
                      "warn": "#FFB300", "error": "#e74c3c"}
            safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            status_lbl.set_markup(
                f'<span foreground="{colors.get(kind, "#888888")}" '
                f'size="small">{safe}</span>'
            )

        def make_label(text):
            lbl = Gtk.Label()
            lbl.set_markup(f'<span foreground="#888888" size="small">{text}</span>')
            lbl.set_halign(Gtk.Align.END)
            lbl.set_valign(Gtk.Align.CENTER)
            return lbl

        def make_entry(placeholder, secret=False):
            entry = Gtk.Entry()
            entry.set_placeholder_text(placeholder)
            entry.set_hexpand(True)
            entry.set_visibility(not secret)
            entry.get_style_context().add_class("cred-entry")
            if secret:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                row.pack_start(entry, True, True, 0)
                toggle = Gtk.Button(label="Show")
                toggle.get_style_context().add_class("neutral-btn")
                def on_toggle(btn, e=entry):
                    vis = not e.get_visibility()
                    e.set_visibility(vis)
                    btn.set_label("Hide" if vis else "Show")
                toggle.connect("clicked", on_toggle)
                row.pack_start(toggle, False, False, 0)
                return entry, row
            return entry, entry

        def note(markup_text):
            lbl = Gtk.Label()
            lbl.set_markup(markup_text)
            lbl.set_halign(Gtk.Align.START)
            lbl.set_line_wrap(True)
            lbl.set_xalign(0.0)
            return lbl

        def render(service):
            for child in body.get_children():
                body.remove(child)
            state["service"] = service
            state["entries"] = {}

            cfg_path = self._streamrip_config_path()
            if not os.path.exists(cfg_path):
                # streamrip is bundled on packaged Windows (and may be on PATH
                # elsewhere), so try to create the config right here — that lets
                # a first-run user paste an ARL and download without any manual
                # `rip config reset` step.
                self._ensure_streamrip_config()
            if not os.path.exists(cfg_path):
                state["config_ok"] = False
                body.pack_start(note(
                    '<span foreground="#FFB300" size="small">'
                    'streamrip config.toml was not found at:\n'
                    f'<tt>{cfg_path}</tt>\n\n'
                    'It must exist before credentials can be saved.</span>'
                ), False, False, 0)
                fix_btn = Gtk.Button(label="Run  rip config reset")
                fix_btn.get_style_context().add_class("neutral-btn")
                fix_btn.set_halign(Gtk.Align.START)
                def on_fix(_b):
                    rip = self._streamrip_cmd()
                    if not rip:
                        set_status(
                            "rip was not found. Install streamrip, then run "
                            "`rip config reset` in a terminal.", "error")
                        return
                    try:
                        subprocess.run(rip + ["config", "reset"],
                                       capture_output=True, text=True, timeout=30)
                    except Exception:
                        pass
                    if os.path.exists(cfg_path):
                        set_status(
                            "config.toml created. You can now enter credentials.",
                            "ok")
                        render(state["service"])
                    else:
                        set_status(
                            "Could not create config.toml automatically. Run "
                            "`rip config reset` in a terminal, then reopen "
                            "this dialog.", "error")
                fix_btn.connect("clicked", on_fix)
                body.pack_start(fix_btn, False, False, 0)
                body.pack_start(note(
                    '<span foreground="#666666" size="small">'
                    'Or run this in a terminal:  <tt>rip config reset</tt></span>'
                ), False, False, 0)
                body.show_all()
                return

            state["config_ok"] = True
            existing = self._read_streamrip_section(cfg_path, service)

            if service == "qobuz":
                grid = Gtk.Grid()
                grid.set_column_spacing(12)
                grid.set_row_spacing(8)
                email_entry, email_w = make_entry("you@example.com")
                cur_email = (existing.get("email")
                             or existing.get("email_or_userid") or "")
                if cur_email:
                    email_entry.set_text(cur_email)
                pass_entry, pass_w = make_entry(
                    "leave blank to keep current", secret=True)
                grid.attach(make_label("Email / Username"), 0, 0, 1, 1)
                grid.attach(email_w, 1, 0, 1, 1)
                grid.attach(make_label("Password"), 0, 1, 1, 1)
                grid.attach(pass_w, 1, 1, 1, 1)
                body.pack_start(grid, False, False, 0)
                body.pack_start(note(
                    '<span foreground="#666666" size="small">'
                    'Qobuz signs in with an email/username and password. The '
                    'password is hidden by default and is never logged. Leave '
                    'it blank to keep the one already saved.</span>'
                ), False, False, 0)
                state["entries"] = {"email": email_entry, "password": pass_entry}

            elif service == "deezer":
                rec = deezer.RECOMMENDED_NOTE.replace("&", "&amp;").replace(
                    "<", "&lt;").replace(">", "&gt;")
                body.pack_start(note(
                    '<span foreground="#4CAF50" size="small">'
                    f'⭐  {rec}</span>'
                ), False, False, 0)
                grid = Gtk.Grid()
                grid.set_column_spacing(12)
                grid.set_row_spacing(8)
                arl_entry, arl_w = make_entry(
                    "leave blank to keep current", secret=True)
                grid.attach(make_label("ARL Token"), 0, 0, 1, 1)
                grid.attach(arl_w, 1, 0, 1, 1)
                body.pack_start(grid, False, False, 0)
                body.pack_start(note(
                    '<span foreground="#FFB300" size="small">'
                    'Deezer does not use email/password. streamrip '
                    'authenticates with an ARL token (a value copied from the '
                    'Deezer website cookie). Paste it above.</span>'
                ), False, False, 0)
                if existing.get("arl"):
                    body.pack_start(note(
                        '<span foreground="#666666" size="small">'
                        'An ARL is already configured. Leave the field blank '
                        'to keep it.</span>'
                    ), False, False, 0)
                deezer_row = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                deezer_row.set_halign(Gtk.Align.START)
                test_deezer_btn = Gtk.Button(label="Test Deezer Setup")
                test_deezer_btn.get_style_context().add_class("neutral-btn")

                def on_test_deezer(_b):
                    msg, kind = deezer.deezer_setup_summary(
                        self._streamrip_config_path())
                    if self._find_rip_path() is None:
                        msg += "  Note: rip was not found in PATH."
                        if kind == "ok":
                            kind = "warn"
                    set_status(msg, kind)

                test_deezer_btn.connect("clicked", on_test_deezer)
                deezer_row.pack_start(test_deezer_btn, False, False, 0)
                body.pack_start(deezer_row, False, False, 0)
                body.pack_start(note(
                    '<span foreground="#666666" size="small">'
                    'Test Deezer Setup checks your saved configuration only '
                    '(ARL present, quality in range). It never downloads a '
                    'full album or reveals your ARL.</span>'
                ), False, False, 0)
                guidance = "\n".join(
                    "• " + g.replace("&", "&amp;").replace(
                        "<", "&lt;").replace(">", "&gt;")
                    for g in deezer.url_guidance())
                body.pack_start(note(
                    '<span foreground="#888888" size="small">'
                    f'<b>Pasting Deezer links:</b>\n{guidance}</span>'
                ), False, False, 0)
                state["entries"] = {"arl": arl_entry}

            else:  # tidal
                body.pack_start(note(
                    '<span foreground="#FFB300" size="small">'
                    'TIDAL has no email/password login — it cannot be set up '
                    'like Qobuz.</span>'
                ), False, False, 0)
                body.pack_start(note(
                    '<span foreground="#888888" size="small">'
                    '<b>Why?</b> TIDAL’s API only offers an OAuth 2.0 '
                    '<b>device authorization</b> sign-in (the “approve this '
                    'device” browser step). It has no password-grant endpoint, '
                    'so streamrip — and therefore Auryn — cannot accept a TIDAL '
                    'email/password the way it does for Qobuz. This is a TIDAL '
                    'platform limitation, not an Auryn restriction. (Qobuz uses '
                    'email/password; Deezer uses an ARL token; TIDAL uses '
                    'device login.)</span>'
                ), False, False, 0)
                body.pack_start(note(
                    '<span foreground="#888888" size="small">'
                    'Use <b>TIDAL Setup…</b> below: streamrip prints a login '
                    'link, you approve this device in your browser, and '
                    'streamrip stores and refreshes the tokens in its own '
                    'config.toml. Auryn never sees or stores a TIDAL '
                    'password. If a previous login is corrupt or keeps '
                    'prompting, use <b>Repair TIDAL Session</b>.</span>'
                ), False, False, 0)
                tidal_row = Gtk.Box(
                    orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                tidal_row.set_halign(Gtk.Align.START)
                tidal_btn = Gtk.Button(label="TIDAL Setup…")
                repair_conn_btn = Gtk.Button(label="Repair TIDAL Session")
                test_conn_btn = Gtk.Button(label="Test TIDAL Connection")
                for _b in (tidal_btn, repair_conn_btn, test_conn_btn):
                    _b.get_style_context().add_class("neutral-btn")

                def on_tidal_setup(_b):
                    GLib.idle_add(self._show_tidal_setup_dialog)
                    dlg.response(Gtk.ResponseType.CANCEL)

                def on_repair_conn(_b):
                    cfg_p = self._streamrip_config_path()
                    if not os.path.exists(cfg_p):
                        set_status("streamrip config.toml not found — nothing "
                                   "to repair. Create it first.", "warn")
                        return
                    GLib.idle_add(self._show_tidal_auth_corrupted_dialog)
                    dlg.response(Gtk.ResponseType.CANCEL)

                def on_test_conn(_b):
                    msg, kind = self._tidal_connection_summary(
                        self._streamrip_config_path())
                    if self._find_rip_path() is None:
                        msg += "  Note: rip was not found in PATH."
                        kind = "warn" if kind == "ok" else kind
                    set_status(msg, kind)
                    if tidal_auth.AUTH_DEBUG:
                        self._auth_log(
                            tidal_auth.auth_debug_report(
                                self._streamrip_config_path()) + "\n", "dim")

                tidal_btn.connect("clicked", on_tidal_setup)
                repair_conn_btn.connect("clicked", on_repair_conn)
                test_conn_btn.connect("clicked", on_test_conn)
                tidal_row.pack_start(tidal_btn, False, False, 0)
                tidal_row.pack_start(repair_conn_btn, False, False, 0)
                tidal_row.pack_start(test_conn_btn, False, False, 0)
                body.pack_start(tidal_row, False, False, 0)
                state["entries"] = {}

            body.show_all()

        def on_combo_changed(c):
            sid = c.get_active_id()
            if sid:
                set_status("")
                render(sid)

        combo.connect("changed", on_combo_changed)
        render("deezer")
        dlg.show_all()

        while True:
            resp = dlg.run()

            if resp == RESP_TEST:
                service = state["service"]
                cfg_path = self._streamrip_config_path()
                if not os.path.exists(cfg_path):
                    set_status("config.toml not found — create it first.", "error")
                    continue
                rip_ok = self._find_rip_path() is not None
                saved = self._read_streamrip_section(cfg_path, service)
                if service == "qobuz":
                    has_email = bool(saved.get("email")
                                     or saved.get("email_or_userid"))
                    has_pass = bool(saved.get("password")
                                    or saved.get("password_or_token"))
                    if has_email and has_pass:
                        msg, kind = ("Qobuz email and password are present in "
                                     "config.toml.", "ok")
                    else:
                        msg, kind = ("Qobuz credentials are incomplete in "
                                     "config.toml. Save them first.", "warn")
                elif service == "deezer":
                    msg, kind = deezer.deezer_setup_summary(cfg_path)
                else:
                    msg, kind = self._tidal_connection_summary(cfg_path)
                if not rip_ok:
                    msg += "  Note: rip was not found in PATH."
                    if kind == "ok":
                        kind = "warn"
                set_status(msg, kind)
                continue

            if resp == Gtk.ResponseType.OK:
                if not state.get("config_ok"):
                    set_status(
                        "config.toml is missing. Create it before saving.",
                        "error")
                    continue
                service = state["service"]
                cfg_path = self._streamrip_config_path()

                if service == "tidal":
                    set_status(
                        "TIDAL has no email/password to save. Use the "
                        "TIDAL Setup… button to log in.", "info")
                    continue

                entries = state["entries"]
                if service == "qobuz":
                    email = entries["email"].get_text().strip()
                    password = entries["password"].get_text()
                    if not email and not password:
                        set_status(
                            "Enter an email/username and password.", "warn")
                        continue
                    updates = {}
                    if email:
                        updates["email"] = email
                    if password:
                        updates["password"] = password
                    ok, err = self._write_streamrip_section(
                        cfg_path, "qobuz", updates,
                        {"email": ["email", "email_or_userid"],
                         "password": ["password", "password_or_token"]},
                    )
                    if ok:
                        GLib.idle_add(
                            self._log,
                            "🔐  Qobuz credentials saved to streamrip config.\n",
                            "info")
                        dlg.destroy()
                        return
                    set_status(err or "Could not save credentials.", "error")
                    continue

                if service == "deezer":
                    arl = entries["arl"].get_text().strip()
                    if not arl:
                        set_status("Enter a Deezer ARL token.", "warn")
                        continue
                    if not os.path.exists(cfg_path):
                        self._ensure_streamrip_config()
                    ok, err = self._write_streamrip_section(
                        cfg_path, "deezer", {"arl": arl}, {"arl": ["arl"]},
                    )
                    if ok:
                        GLib.idle_add(
                            self._log,
                            "🔐  Deezer ARL saved to streamrip config.\n",
                            "info")
                        dlg.destroy()
                        return
                    set_status(err or "Could not save credentials.", "error")
                    continue

            break

        dlg.destroy()

    def _show_diagnostics(self, *_):
        buf_io = io.StringIO()
        with contextlib.redirect_stdout(buf_io), contextlib.redirect_stderr(buf_io):
            try:
                ok = run_doctor(verbose=True)
            except Exception as exc:
                ok = False
                print(f"FAIL  Diagnostics raised an exception: {exc}")
        output = buf_io.getvalue() or "(no output)"
        cfg_path = self._streamrip_config_path()
        # Always show the concise, secret-free auth panel (field presence,
        # token_expiry validity, whether the refresh flow is possible).
        try:
            output += "\n\n" + tidal_auth.render_auth_panel(cfg_path)
        except Exception as exc:
            output += ("\n\n(TIDAL auth panel unavailable"
                       + (f": {exc!r}" if tidal_auth.AUTH_DEBUG else "")
                       + ")")
        # The fuller masked report (config path + token fingerprints) is only
        # appended in auth-debug mode so the default panel stays lean and
        # never risks dumping a raw traceback.
        if tidal_auth.AUTH_DEBUG:
            try:
                output += "\n\n" + tidal_auth.auth_debug_report(cfg_path)
            except Exception as exc:
                output += f"\n\n(TIDAL auth report unavailable: {exc!r})"
        else:
            output += ("\n\nTip: set AURYN_DEBUG_AUTH=1 (or run with "
                       "--debug-auth) for full masked TIDAL auth "
                       "diagnostics and live auth logging.")

        dlg = Gtk.Dialog(
            title="Auryn Diagnostics",
            transient_for=self.window,
            modal=True,
        )
        copy_btn = dlg.add_button("Copy", 1)
        save_btn = dlg.add_button("Save", 2)
        dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        dlg.set_default_size(720, 480)

        def _on_copy(_btn):
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(output, -1)
            clipboard.store()

        def _on_save(_btn):
            chooser = Gtk.FileChooserDialog(
                title="Save Diagnostics",
                transient_for=dlg,
                action=Gtk.FileChooserAction.SAVE,
            )
            chooser.add_buttons(
                "Cancel", Gtk.ResponseType.CANCEL,
                "Save", Gtk.ResponseType.ACCEPT,
            )
            chooser.set_current_name("auryn_diagnostics.txt")
            chooser.set_do_overwrite_confirmation(True)
            try:
                if chooser.run() == Gtk.ResponseType.ACCEPT:
                    path = chooser.get_filename()
                    if path:
                        try:
                            with open(path, "w", encoding="utf-8") as f:
                                f.write(output)
                        except OSError as exc:
                            err = Gtk.MessageDialog(
                                transient_for=dlg,
                                modal=True,
                                message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.OK,
                                text="Could not save diagnostics",
                            )
                            err.format_secondary_text(str(exc))
                            err.run()
                            err.destroy()
            finally:
                chooser.destroy()

        copy_btn.connect("clicked", _on_copy)
        save_btn.connect("clicked", _on_save)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.get_buffer().set_text(output)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.add(text_view)

        content = dlg.get_content_area()
        content.set_border_width(8)
        content.pack_start(scrolled, True, True, 0)
        content.show_all()

        dlg.run()
        dlg.destroy()

    def _show_about(self, *_):
        dlg = Gtk.AboutDialog()
        dlg.set_transient_for(self.window)
        dlg.set_program_name("Auryn")
        dlg.set_version(f"v{APP_VERSION}")
        dlg.set_comments("GUI wrapper for streamrip\nDeezer • Qobuz • Tidal • SoundCloud")
        dlg.set_copyright("© 2025 TheZupZup")
        dlg.set_license_type(Gtk.License.GPL_3_0)
        dlg.run()
        dlg.destroy()

    # ── Lyrics Logic ─────────────────────────────────────────────────────────

    def _fetch_and_apply_lyrics(self, artist, track):
        try:
            q_artist = urllib.parse.quote(artist)
            q_track = urllib.parse.quote(track)
            url = f"https://lrclib.net/api/get?artist_name={q_artist}&track_name={q_track}"
            
            req = urllib.request.Request(url, headers={"User-Agent": "Auryn/0.1.1 (GTK3)"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
                
            lyrics = data.get("syncedLyrics") or data.get("plainLyrics")
            if lyrics:
                # Nettoyage et échappement
                safe_track = track.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                safe_lyrics = lyrics.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                clean_lyrics = re.sub(r'\[\d+:\d+\.\d+\]', '', safe_lyrics).strip()
                markup = f'<span foreground="#FF6B35" weight="bold" size="large">{safe_track}</span>\n\n{clean_lyrics}'
                GLib.idle_add(self.lyrics_label.set_markup, markup)
            else:
                track_esc = track.replace("&", "&amp;").replace("<", "&lt;")
                GLib.idle_add(self.lyrics_label.set_markup, f'<span foreground="#555555"><i>Lyrics not found for: {track_esc}</i></span>')
        except Exception as e:
            err_esc = str(e).replace("&", "&amp;").replace("<", "&lt;")
            GLib.idle_add(self.lyrics_label.set_markup, f'<span foreground="#e74c3c"><i>Error fetching lyrics: {err_esc}</i></span>')

    def _set_lyrics(self, text):
        # Cette méthode attend du markup déjà prêt ou du texte simple
        self.lyrics_label.set_markup(text)

    def _on_quit(self, *_):
        if self._process and self._process.poll() is None:
            self._process.terminate()
        Gtk.main_quit()


if __name__ == "__main__":
    # PyInstaller best practice: keep any library that uses multiprocessing
    # from re-launching the GUI when the frozen exe re-execs itself.
    import multiprocessing
    multiprocessing.freeze_support()

    # Multi-call entry point: a packaged build runs the bundled streamrip in
    # this same frozen interpreter via `Auryn.exe --run-streamrip <args…>`.
    # Handle it first, before importing GTK, so the streamrip child never
    # opens a window. Everything after the flag is passed to streamrip as-is.
    if streamrip_exec.RUN_STREAMRIP_FLAG in sys.argv:
        _idx = sys.argv.index(streamrip_exec.RUN_STREAMRIP_FLAG)
        raise SystemExit(streamrip_exec.dispatch_streamrip(sys.argv[_idx + 1:]))

    if IS_MACOS:
        print("Auryn is not supported on macOS yet. Please use Linux or Windows.")
        raise SystemExit(1)

    if "--version" in sys.argv:
        print(f"{APP_NAME} {APP_VERSION}")
        raise SystemExit(0)

    if "--debug-auth" in sys.argv:
        # Developer auth-diagnostics mode: turn on verbose, scrubbed TIDAL
        # auth logging for the rest of this process.
        os.environ["AURYN_DEBUG_AUTH"] = "1"
        tidal_auth.AUTH_DEBUG = True

    if "--doctor" in sys.argv:
        verbose = ("--verbose" in sys.argv or "-v" in sys.argv
                   or "--debug-auth" in sys.argv)
        if "--report" in sys.argv:
            buf_io = io.StringIO()
            with contextlib.redirect_stdout(buf_io), contextlib.redirect_stderr(buf_io):
                try:
                    ok = run_doctor(verbose=verbose)
                except Exception as exc:
                    ok = False
                    print(f"FAIL  Diagnostics raised an exception: {exc}")
            report_path = os.path.abspath("auryn_diagnostics.txt")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(buf_io.getvalue() or "(no output)")
            print(f"Diagnostics saved to {report_path}")
            raise SystemExit(0 if ok else 1)
        raise SystemExit(0 if run_doctor(verbose=verbose) else 1)

    _import_gtk()
    app = AurynApp()
    Gtk.main()
