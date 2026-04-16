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

SYSTEM_NAME = platform.system()
IS_WINDOWS = SYSTEM_NAME == "Windows"
IS_MACOS = SYSTEM_NAME == "Darwin"
IS_UNSUPPORTED_OS = IS_WINDOWS or IS_MACOS

gi = None
pty = None
fcntl = None 

if not IS_UNSUPPORTED_OS:
    import gi
    import pty
    import fcntl
    
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
"""

QUALITY_LABELS = ["MP3 128", "MP3 320", "FLAC 16/44.1", "FLAC 24/96+", "Max (MQA)"]
QUALITY_VALUES = ["0",       "1",       "2",            "3",           "4"]


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
    xdg = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg, "streamrip")


def toml_escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
        self.btn_setup     = self.builder.get_object("btn_setup")
        self.btn_choose    = self.builder.get_object("btn_choose_folder")
        self.btn_open      = self.builder.get_object("btn_open_folder")
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
        self._process      = None
        self._dest_folder  = os.path.expanduser("~/Music")
        self._track_done   = 0
        self._total_tracks = 0

        # ── Forcer can-focus sur les widgets interactifs ──
        self.url_entry.set_can_focus(True)
        self.btn_download.set_can_focus(True)
        self.btn_stop.set_can_focus(True)
        self.btn_choose.set_can_focus(True)
        self.btn_open.set_can_focus(True)
        self.btn_log.set_can_focus(True)
        self.btn_about.set_can_focus(True)
        self.btn_setup.set_can_focus(True)
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
        self.btn_choose.connect("clicked", self._choose_folder)
        self.btn_open.connect("clicked", self._open_folder)
        self.btn_log.connect("clicked", self._open_log_folder)

        for i, cb in enumerate(self._quality_checks):
            cb.connect("toggled", self._on_quality_toggled, i)

        # ── Afficher ──
        self.window.show_all()
        self.btn_stop.hide()
        GLib.idle_add(self._first_run_health_check)

    # ── Qualité ──────────────────────────────────────────────────────────────

    def _on_quality_toggled(self, widget, idx):
        if widget.get_active():
            for i, cb in enumerate(self._quality_checks):
                if i != idx:
                    cb.handler_block_by_func(self._on_quality_toggled)
                    cb.set_active(False)
                    cb.handler_unblock_by_func(self._on_quality_toggled)

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
            self.folder_lbl.set_markup(
                f'<span foreground="#FF6B35" size="small">📁  {self._dest_folder}</span>')
        dlg.destroy()

    def _open_folder(self, *_):
        os.makedirs(self._dest_folder, exist_ok=True)
        subprocess.Popen(["xdg-open", self._dest_folder])

    def _open_log_folder(self, *_):
        log_dir = os.path.expanduser("~/.local/state/Auryn")
        os.makedirs(log_dir, exist_ok=True)
        subprocess.Popen(["xdg-open", log_dir])

    # ── Download ─────────────────────────────────────────────────────────────

    def _on_download(self, *_):
        url = self.url_entry.get_text().strip()
        if not url:
            self._set_status("⚠   Please paste a URL first.", "error")
            return
        ok, issues = self._run_preflight_checks(auto_fix=False)
        if not ok:
            self._set_status("❌  Setup issue detected — open Setup.", "error")
            self._log("❌  Preflight checks failed:\n", "error")
            for issue in issues:
                self._log(f"   • {issue}\n", "error")
            return
        os.makedirs(self._dest_folder, exist_ok=True)
        self.btn_download.set_sensitive(False)
        self.btn_stop.show()
        self.btn_stop.set_sensitive(True)
        self.progress_bar.set_fraction(0)
        self._clear_log()
        self._reset_meta()
        self._track_done   = 0
        self._total_tracks = 0
        self._set_status("⏳   Fetching album info...", "info")
        self._set_lyrics('<span foreground="#444444"><i>Lyrics will appear here during download...</i></span>')
        quality = self._get_quality()
        threading.Thread(target=self._thread_main, args=(url, quality), daemon=True).start()

    def _on_stop(self, *_):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self._log("⏹   Download stopped by user.\n", "error")
            self._set_status("Stopped.", "error")
        self.btn_stop.set_sensitive(False)

    def _thread_main(self, url, quality):
        service, item_id = detect_service_and_id(url)
        if service == "qobuz" and item_id:
            data = fetch_qobuz_meta(item_id)
            if data and not data.get("status") == "error":
                GLib.idle_add(self._apply_qobuz_meta, data)
        elif service == "deezer" and item_id:
            data = fetch_deezer_album(item_id)
            if data and not data.get("error"):
                GLib.idle_add(self._apply_deezer_meta, data)
        elif service == "deezer_track" and item_id:
            data = fetch_deezer_track_album(item_id)
            if data and not data.get("error"):
                GLib.idle_add(self._apply_deezer_meta, data)
                # For single track, fetch lyrics immediately
                artist = data.get("artist", {}).get("name")
                title = data.get("title")
                if artist and title:
                    threading.Thread(target=self._fetch_and_apply_lyrics, args=(artist, title), daemon=True).start()
        self._run_download(url, quality)

    # ── Métadonnées ───────────────────────────────────────────────────────────

    def _apply_deezer_meta(self, data):
        def sm(key, value):
            if value:
                txt = str(value).strip()[:28].replace("&","&amp;").replace("<","&lt;")
                self._meta[key].set_markup(f'<span foreground="#e8e8e8" size="small">{txt}</span>')
        sm("Album Artist",  data.get("artist", {}).get("name", ""))
        sm("Album",         data.get("title", ""))
        sm("Total Tracks",  data.get("nb_tracks", ""))
        sm("UPC",           data.get("upc", ""))
        sm("Release Date",  data.get("release_date", ""))
        sm("Album Quality", "FLAC 16-bit / 44.1 kHz")
        cover_url = data.get("cover_xl") or data.get("cover_big") or data.get("cover_medium")
        if cover_url:
            threading.Thread(target=self._load_cover, args=(cover_url,), daemon=True).start()

    def _apply_qobuz_meta(self, data):
        def sm(key, value):
            if value:
                txt = str(value).strip()[:30].replace("&","&amp;").replace("<","&lt;")
                self._meta[key].set_markup(f'<span foreground="#e8e8e8" size="small">{txt}</span>')
        artist = data.get("artist", {}).get("name", "") or data.get("performer", {}).get("name", "")
        sm("Album Artist",  artist)
        sm("Album",         data.get("title", ""))
        sm("Total Tracks",  data.get("tracks_count", data.get("tracks", {}).get("total", "")))
        sm("UPC",           data.get("upc", ""))
        sm("Release Date",  (data.get("release_date_original") or data.get("released_at") or "")[:10])
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
                          '<span foreground="#555555" size="small">Cover Art</span>')

    def _load_cover(self, cover_url):
        pb = download_cover(cover_url, size=185)
        if pb:
            GLib.idle_add(self.cover_img.set_from_pixbuf, pb)
            GLib.idle_add(self.cover_lbl.set_markup,
                          '<span foreground="#555555" size="small">Cover Art</span>')

    # ── Lancement streamrip ───────────────────────────────────────────────────

    def _find_rip_path(self):
        for candidate in [
            os.path.expanduser("~/.local/bin/rip"),
            "/usr/local/bin/rip",
            "/usr/bin/rip",
        ]:
            if os.path.isfile(candidate):
                return candidate
        try:
            result = subprocess.run(["which", "rip"], capture_output=True, text=True)
            if result.returncode == 0:
                found = result.stdout.strip()
                if found:
                    return found
        except Exception:
            pass
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
                issues.append("streamrip config.toml is missing (run: rip config reset).")

        if not self._check_dest_writable():
            issues.append(f"Destination is not writable: {self._dest_folder}")

        return (len(issues) == 0, issues)

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

    def _update_config(self, cfg, pattern, replacement, first_only=False):
        if not os.path.exists(cfg):
            return
        try:
            with open(cfg, 'r') as f:
                content = f.read()
            
            if first_only:
                new_content = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
            else:
                new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            
            with open(cfg, 'w') as f:
                f.write(new_content)
        except Exception as e:
            GLib.idle_add(self._log, f"⚠  Config update error: {e}\n", "error")

    def _apply_stored_credentials(self, cfg):
        acc_path = os.path.expanduser("~/.config/Auryn/accounts.json")
        if not os.path.exists(acc_path):
            return

        try:
            with open(acc_path, 'r') as f:
                acc = json.load(f)
        except Exception as e:
            GLib.idle_add(self._log, f"⚠  Could not read accounts.json: {e}\n", "error")
            return

        GLib.idle_add(self._log, "🔐  Applying stored credentials...\n", "info")
        
        # Qobuz
        if "qobuz" in acc:
            q = acc["qobuz"]
            if q.get("email"):
                self._update_config(cfg, r"^email = .*", f'email = "{toml_escape(q["email"])}"')
            if q.get("password"):
                self._update_config(cfg, r"^password = .*", f'password = "{toml_escape(q["password"])}"')
        
        # Tidal
        if "tidal" in acc:
            t = acc["tidal"]
            if t.get("user_id"):
                 self._update_config(cfg, r"^user_id = .*", f'user_id = "{toml_escape(t["user_id"])}"')
            if t.get("token"):
                 self._update_config(cfg, r"^token = .*", f'token = "{toml_escape(t["token"])}"')

        # Deezer
        if "deezer" in acc:
            d = acc["deezer"]
            if d.get("arl"):
                 self._update_config(cfg, r"^arl = .*", f'arl = "{toml_escape(d["arl"])}"')

        # SoundCloud
        if "soundcloud" in acc:
            s = acc["soundcloud"]
            if s.get("oauth_token"):
                 self._update_config(cfg, r"^oauth_token = .*", f'oauth_token = "{toml_escape(s["oauth_token"])}"')

    def _run_download(self, url, quality):
        cfg_path = os.path.join(resolve_config_dir(), "config.toml")
        cfg = os.path.expanduser(cfg_path)
        db = os.path.join(resolve_config_dir(), "downloads.db")

        if self.cb_clear_cache.get_active() and os.path.exists(db):
            try:
                os.remove(db)
                GLib.idle_add(self._log, "🧹  Cache cleared.\n", "info")
            except Exception:
                pass

        if os.path.exists(cfg):
            self._apply_stored_credentials(cfg)
            safe_folder = toml_escape(self._dest_folder)
            self._update_config(cfg, r"^quality = .*", f"quality = {quality}")
            self._update_config(cfg, r"^use_auth_token = .*", "use_auth_token = true")
            self._update_config(cfg, r"^folder = .*", f'folder = "{safe_folder}"', first_only=True)

        GLib.idle_add(self._log, f"🌐  URL     : {url}\n", "info")
        GLib.idle_add(self._log, f"🎵  Quality : {quality} | Dest : {self._dest_folder}\n", "info")
        GLib.idle_add(self._log, "─" * 60 + "\n", "dim")

        rip_path = self._find_rip_path()

        if not rip_path:
            GLib.idle_add(self._log,
                "❌  streamrip (rip) not found!\n"
                "    Install: pipx install streamrip\n"
                "    Then:    rip config reset\n", "error")
            GLib.idle_add(self._finish, False)
            return

        GLib.idle_add(self._log, f"🔧  Using: {rip_path}\n", "info")

        master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["TERM"] = "xterm-256color"
        env["FORCE_COLOR"] = "1"

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

    # ── Parsing log ──────────────────────────────────────────────────────────

    def _parse_line(self, line):
        lo = line.lower()
        if any(w in lo for w in ["error", "failed", "exception", "traceback"]):
            tag = "error"
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
        else:
            code = self._process.returncode if self._process else -1
            if code != -15:
                self._set_status("❌  Download failed — check the log.", "error")
                self._log("\n❌  Download failed.\n", "error")
        self.btn_download.set_sensitive(True)
        self.btn_stop.hide()
        self.speed_lbl.set_markup("")

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
        colors = {"ok":"#87a556","error":"#e74c3c","track":"#FF6B35","info":"#555555"}
        color = colors.get(style, "#555555")
        safe = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        self.status_lbl.set_markup(f'<span foreground="{color}" size="small">{safe}</span>')

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

    def _show_about(self, *_):
        dlg = Gtk.AboutDialog()
        dlg.set_transient_for(self.window)
        dlg.set_program_name("Auryn")
        dlg.set_version("v0.1.1")
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
    if IS_UNSUPPORTED_OS:
        print("Auryn is not supported on Windows or macOS yet. Please use Linux for now.")
        raise SystemExit(1)

    app = AurynApp()
    Gtk.main()
