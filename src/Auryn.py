#!/usr/bin/env python3
"""
Auryn v0.1.1 — GUI wrapper for streamrip
© 2025 TheZupZup — GNU GPL v3
UI chargée depuis Auryn.ui (Glade)
"""


import os
import re
import shutil
import threading
import subprocess
import urllib.request
import json
import tempfile
import platform
import sys
import io
import time
import contextlib
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.errors import parse_streamrip_error
from core.status import build_status_markup
from core import tidal_auth

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
#url_entry { background-color: #0d0d0d; color: #e8e8e8; border: 1px solid #333; border-radius: 3px; padding: 6px 10px; font-family: 'Ubuntu Mono', monospace; font-size: 12px; caret-color: #FF6B35; }
#url_entry:focus { border-color: #FF6B35; }
.cred-entry { background-color: #0d0d0d; color: #e8e8e8; border: 1px solid #333; border-radius: 3px; padding: 6px 10px; font-family: 'Ubuntu Mono', monospace; font-size: 12px; caret-color: #FF6B35; }
.cred-entry:focus { border-color: #FF6B35; }
#quality_box { background-color: #111111; border: 1px solid #252525; border-radius: 3px; padding: 5px 12px; }
checkbutton { color: #aaaaaa; font-size: 12px; }
checkbutton check { background-color: #0d0d0d; border-color: #444; border-radius: 2px; min-width: 14px; min-height: 14px; }
checkbutton:checked check { background-color: #FF6B35; border-color: #FF6B35; }
checkbutton label:hover { color: #FF6B35; }
.neutral-btn { background-color: #252525; color: #aaaaaa; border: 1px solid #333; border-radius: 3px; padding: 5px 12px; font-size: 11px; }
.neutral-btn:hover { background-color: #2e2e2e; color: #ffffff; border-color: #FF6B35; }
#btn_download { background-color: #FF6B35; color: #ffffff; border: none; border-radius: 3px; padding: 7px 18px; font-size: 13px; font-weight: bold; }
#btn_download:hover { background-color: #ff7d4d; }
#btn_download:disabled { background-color: #333; color: #666; }
#btn_stop { background-color: #c0392b; color: #ffffff; border: none; border-radius: 3px; padding: 7px 16px; font-size: 13px; font-weight: bold; }
#btn_stop:hover { background-color: #e74c3c; }
#log_view { background-color: #080808; color: #bbbbbb; font-family: 'Ubuntu Mono', 'Courier New', monospace; font-size: 11px; padding: 8px; }
#log_scroll { border: 1px solid #252525; border-radius: 3px; }
#lyrics_label { font-family: 'Ubuntu', sans-serif; padding: 4px; }
notebook { background-color: #0d0d0d; border: 1px solid #252525; border-radius: 3px; }
notebook stack { background-color: #0d0d0d; padding: 10px; }
notebook tab { background-color: #111111; color: #888; border: none; padding: 4px 12px; }
notebook tab:checked { background-color: #FF6B35; color: #ffffff; font-weight: bold; }
progressbar trough { background-color: #0d0d0d; border: 1px solid #252525; border-radius: 3px; min-height: 4px; }
progressbar progress { background-color: #FF6B35; border-radius: 3px; min-height: 4px; }
#footer_bar { background-color: #0a0a0a; border-top: 1px solid #222; padding: 3px 12px; min-height: 22px; }
separator { background-color: #252525; }
.history-row { background-color: #0d0d0d; border: 1px solid #1f1f1f; border-radius: 3px; }
.history-row:hover { border-color: #333; }
"""

QUALITY_LABELS = ["MP3 128", "MP3 320", "FLAC 16/44.1", "FLAC 24/96+", "Max (MQA)"]
QUALITY_VALUES = ["0",       "1",       "2",            "3",           "4"]

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
    """Fail-fast environment check; prints only the first problem found."""
    rip_search_paths = [
        os.path.expanduser("~/.local/bin/rip"),
        "/usr/local/bin/rip",
        "/usr/bin/rip",
    ]
    cfg_path = os.path.join(resolve_config_dir(), "config.toml")
    folder = os.path.expanduser("~/Music")

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

    rip_path = shutil.which("rip")
    if not rip_path:
        for _c in rip_search_paths:
            if os.path.isfile(_c):
                rip_path = _c
                break
    if not rip_path:
        print("FAIL  streamrip (rip) not found in PATH or common locations.")
        if verbose:
            print("INFO  Paths searched for rip:")
            print("        $PATH (via shutil.which)")
            for _c in rip_search_paths:
                print(f"        {_c}")
        return False
    if verbose:
        print(f"INFO  rip found at: {rip_path}")

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
        self.cb_clear_cache = self.builder.get_object("cb_clear_cache")
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
        self._cfg_fingerprint_pre   = None

        # ── Forcer can-focus sur les widgets interactifs ──
        self.url_entry.set_can_focus(True)
        self.btn_download.set_can_focus(True)
        self.btn_stop.set_can_focus(True)
        self.btn_choose.set_can_focus(True)
        self.btn_open.set_can_focus(True)
        self.btn_open_downloads.set_can_focus(True)
        self.btn_log.set_can_focus(True)
        self.btn_about.set_can_focus(True)
        self.btn_setup.set_can_focus(True)
        self.btn_credentials.set_can_focus(True)
        self.btn_diagnostics.set_can_focus(True)
        self.btn_add_queue.set_can_focus(True)
        self.btn_clear_queue.set_can_focus(True)
        self.cb_clear_cache.set_can_focus(True)
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
        self.btn_add_queue.connect("clicked", self._on_add_to_queue)
        self.btn_clear_queue.connect("clicked", self._on_clear_queue)

        for i, cb in enumerate(self._quality_checks):
            cb.connect("toggled", self._on_quality_toggled, i)

        # ── Restaurer les préférences enregistrées ──
        self._apply_saved_preferences()

        # ── Afficher ──
        self.window.show_all()
        self.btn_stop.hide()
        self._is_first_launch = is_first_launch()
        if self._is_first_launch:
            GLib.idle_add(self._show_first_launch_welcome)
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

    def _persist_preferences(self):
        self._config["download_folder"] = self._dest_folder
        for i, cb in enumerate(self._quality_checks):
            if cb.get_active():
                self._config["quality_level"] = i
                break
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

        if entry["status"] == "Completed":
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
        GLib.idle_add(self._set_status, "⏳  Preparing download...", "info")
        self._run_download(url, quality)

    # ── Métadonnées ───────────────────────────────────────────────────────────

    def _apply_deezer_meta(self, data):
        def sm(key, value):
            if value:
                txt = str(value).strip()[:28].replace("&","&amp;").replace("<","&lt;")
                self._meta[key].set_markup(f'<span foreground="#e8e8e8" size="small">{txt}</span>')
        artist = data.get("artist", {}).get("name", "")
        album  = data.get("title", "")
        sm("Album Artist",  artist)
        sm("Album",         album)
        sm("Total Tracks",  data.get("nb_tracks", ""))
        sm("UPC",           data.get("upc", ""))
        sm("Release Date",  data.get("release_date", ""))
        sm("Album Quality", "FLAC 16-bit / 44.1 kHz")
        title = self._format_history_title(artist, album)
        self._history_set_title(self._current_history_entry, title)
        self._queue_set_title(self._current_queue_item, title)
        cover_url = data.get("cover_xl") or data.get("cover_big") or data.get("cover_medium")
        if cover_url:
            threading.Thread(target=self._load_cover, args=(cover_url,), daemon=True).start()

    def _apply_qobuz_meta(self, data):
        def sm(key, value):
            if value:
                txt = str(value).strip()[:30].replace("&","&amp;").replace("<","&lt;")
                self._meta[key].set_markup(f'<span foreground="#e8e8e8" size="small">{txt}</span>')
        artist = data.get("artist", {}).get("name", "") or data.get("performer", {}).get("name", "")
        album  = data.get("title", "")
        sm("Album Artist",  artist)
        sm("Album",         album)
        sm("Total Tracks",  data.get("tracks_count", data.get("tracks", {}).get("total", "")))
        sm("UPC",           data.get("upc", ""))
        sm("Release Date",  (data.get("release_date_original") or data.get("released_at") or "")[:10])
        title = self._format_history_title(artist, album)
        self._history_set_title(self._current_history_entry, title)
        self._queue_set_title(self._current_queue_item, title)
        max_q = data.get("maximum_sampling_rate", 0)
        max_b = data.get("maximum_bit_depth", 0)
        if max_q and max_b:
            sm("Album Quality", f"FLAC {max_b}-bit / {max_q} kHz")
        elif data.get("hires_streamable"):
            sm("Album Quality", "Hi-Res FLAC")
        img = data.get("image", {})
        cover_url = img.get("large") or img.get("small") or img.get("thumbnail", "")
        if cover_url:
            cover_url = re.sub(r'_\d+\.jpg', '_max.jpg', cover_url)
            cover_fallback = re.sub(r'_\d+\.jpg', '_600.jpg', cover_url.replace('_max.jpg', '_600.jpg'))
            threading.Thread(
                target=self._load_cover_with_fallback,
                args=(cover_url, cover_fallback), daemon=True
            ).start()

    def _load_cover_with_fallback(self, url1, url2):
        pb = download_cover(url1, size=185)
        if not pb:
            pb = download_cover(url2, size=185)
        if pb:
            GLib.idle_add(self.cover_img.set_from_pixbuf, pb)
            GLib.idle_add(self.cover_lbl.set_markup,
                          '<span foreground="#888888" size="small" letter_spacing="200">COVER</span>')

    def _load_cover(self, cover_url):
        pb = download_cover(cover_url, size=185)
        if pb:
            GLib.idle_add(self.cover_img.set_from_pixbuf, pb)
            GLib.idle_add(self.cover_lbl.set_markup,
                          '<span foreground="#888888" size="small" letter_spacing="200">COVER</span>')

    # ── Lancement streamrip ───────────────────────────────────────────────────

    def _find_rip_path(self):
        found = shutil.which("rip")
        if found:
            return found

        if IS_WINDOWS:
            candidates = []
            appdata = os.environ.get("APPDATA", "")
            localappdata = os.environ.get("LOCALAPPDATA", "")
            userprofile = os.environ.get("USERPROFILE", "")

            if appdata:
                candidates.append(os.path.join(appdata, "Python", "Scripts", "rip.exe"))
                candidates.append(os.path.join(appdata, "pipx", "venvs", "streamrip", "Scripts", "rip.exe"))
            if localappdata:
                python_root = os.path.join(localappdata, "Programs", "Python")
                if os.path.isdir(python_root):
                    for entry in sorted(os.listdir(python_root), reverse=True):
                        if entry.startswith("Python"):
                            candidates.append(
                                os.path.join(python_root, entry, "Scripts", "rip.exe")
                            )
            if userprofile:
                candidates.append(os.path.join(userprofile, ".local", "bin", "rip.exe"))

            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate
        else:
            for candidate in [
                os.path.expanduser("~/.local/bin/rip"),
                "/usr/local/bin/rip",
                "/usr/bin/rip",
            ]:
                if os.path.isfile(candidate):
                    return candidate

        return None

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
        rip_path = self._find_rip_path()
        if not rip_path:
            if IS_WINDOWS:
                issues.append(
                    "streamrip not found — rip.exe must be installed and in PATH. "
                    "Install via: pipx install streamrip (or: pip install streamrip), "
                    "then open a new terminal to refresh PATH."
                )
            else:
                issues.append("streamrip (rip) is not installed or not in PATH.")

        cfg_path = os.path.join(resolve_config_dir(), "config.toml")
        if not os.path.exists(cfg_path):
            if auto_fix and rip_path:
                try:
                    result = subprocess.run([rip_path, "config", "reset"], capture_output=True, text=True)
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
        rip_found = shutil.which("rip") is not None
        body = (
            "The setup wizard will help you configure:\n"
            "  • Download folder\n"
            "  • streamrip credentials and config\n\n"
        )
        if rip_found:
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
        self._tidal_auth_required = False
        self._tidal_auth_corrupted = False
        self._tb_noise_notified = False
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
            for svc in ("qobuz", "tidal", "deezer", "soundcloud"):
                edits.append({"section": svc, "key": "quality",
                              "value": str(quality), "quote": False})

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

        rip_path = self._find_rip_path()

        if not rip_path:
            if IS_WINDOWS:
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

        GLib.idle_add(self._log, f"🔧  Using: {rip_path}\n", "info")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["TERM"] = "xterm-256color"
        env["FORCE_COLOR"] = "1"

        if IS_WINDOWS:
            self._run_download_windows(rip_path, url, env)
            return

        master_fd, slave_fd = pty.openpty()

        try:
            self._process = subprocess.Popen(
                [rip_path, "url", url],
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

    def _run_download_windows(self, rip_path, url, env):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                [rip_path, "url", url],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
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
        def sm(key, value):
            if value:
                txt = str(value).strip()[:30].replace("&","&amp;").replace("<","&lt;")
                current = self._meta[key].get_text()
                if current == "—" or not current:
                    self._meta[key].set_markup(f'<span foreground="#e8e8e8" size="small">{txt}</span>')

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
            artist = self._meta["Album Artist"].get_text()
            if artist != "—" and artist:
                threading.Thread(target=self._fetch_and_apply_lyrics, args=(artist, track_name), daemon=True).start()

        m = re.search(r'Release\s+date[:\s]+(\d{4}[-/]\d{2}[-/]\d{2})', line, re.I)
        if m: sm("Release Date", m.group(1))

        m = re.search(r'(?:UPC|Barcode)[:\s]+(\d{8,14})', line, re.I)
        if m: sm("UPC", m.group(1))

        if self._meta["Album Quality"].get_text() in ("—", ""):
            for pat in [
                r'(FLAC\s+\d+\s*bit.{1,20}kHz)',
                r'(\d+\s*bit\s*/\s*[\d.]+\s*kHz)',
                r'(MP3\s+\d+\s*kbps?)',
                r'(Hi.?Res\s+FLAC)',
            ]:
                m = re.search(pat, line, re.I)
                if m: sm("Album Quality", m.group(1)); break

    # ── Fin ───────────────────────────────────────────────────────────────────

    def _finish(self, success):
        if success:
            self._set_status("✅  Download complete!", "ok")
            self.progress_bar.set_fraction(1.0)
            self._log("\n✅  All downloads finished!\n", "ok")
            folder = self._detect_new_folder(self._dest_folder, self._dest_dirs_snapshot) or self._dest_folder
            self._history_set_status(self._current_history_entry, "Completed", folder=folder)
            self._queue_set_status(self._current_queue_item, "Completed")
        else:
            code = self._process.returncode if self._process else -1
            if code != -15:
                status_msg = self._last_known_error or "❌  Download failed — check the log."
                self._set_status(status_msg, "error")
                self._log("\n❌  Download failed.\n", "error")
            self._history_set_status(self._current_history_entry, "Failed")
            self._queue_set_status(self._current_queue_item, "Failed")

        self._post_download_config_audit()
        user_stopped = (self._process is not None
                        and self._process.returncode == -15)
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
        buf = self.log_view.get_buffer()
        end = buf.get_end_iter()
        if tag:
            buf.insert_with_tags_by_name(end, text, tag)
        else:
            buf.insert(end, text)
        adj = self._scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def _clear_log(self):
        self.log_view.get_buffer().set_text("")

    def _set_status(self, text, style="info"):
        self.status_lbl.set_markup(build_status_markup(text, style))

    def _reset_meta(self):
        for lbl in self._meta.values():
            lbl.set_markup('<span foreground="#333333" size="small">—</span>')
        self._set_lyrics('<span foreground="#333333" size="small">—</span>')
        self._set_placeholder_cover()
        self.speed_lbl.set_markup("")

    def _set_placeholder_cover(self):
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 185, 185)
        pb.fill(0x161616ff)
        self.cover_img.set_from_pixbuf(pb)

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
                rip = self._find_rip_path()
                if not rip:
                    set_status("rip was not found. Install streamrip, then "
                               "run `rip config reset` in a terminal.", "error")
                    return
                try:
                    subprocess.run([rip, "config", "reset"],
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
            rip = self._find_rip_path()
            if not rip:
                GLib.idle_add(finish_worker, {
                    "state": "error",
                    "message": "rip (streamrip) was not found in PATH. "
                               "Install streamrip first."})
                return

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            creationflags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                             if IS_WINDOWS else 0)
            try:
                proc = subprocess.Popen(
                    [rip, "url", TIDAL_LOGIN_PROBE_URL],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, bufsize=1,
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
        for sid, label in (("qobuz", "Qobuz"), ("deezer", "Deezer"), ("tidal", "TIDAL")):
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
                    rip = self._find_rip_path()
                    if not rip:
                        set_status(
                            "rip was not found. Install streamrip, then run "
                            "`rip config reset` in a terminal.", "error")
                        return
                    try:
                        subprocess.run([rip, "config", "reset"],
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
        render("qobuz")
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
                    if saved.get("arl"):
                        msg, kind = ("Deezer ARL is present in config.toml.",
                                     "ok")
                    else:
                        msg, kind = ("No Deezer ARL found in config.toml. "
                                     "Save it first.", "warn")
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
        dlg.set_comments("GUI wrapper for streamrip\nQobuz • Deezer • Tidal • SoundCloud")
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
