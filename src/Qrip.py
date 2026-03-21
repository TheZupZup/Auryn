#!/usr/bin/env python3
"""
Qrip v0.1.1 — GUI wrapper for streamrip
© 2025 TheZupZup — GNU GPL v3
"""

import gi
import os
import re
import pty
import fcntl
import threading
import subprocess
import urllib.request
import json
import tempfile

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
progressbar trough { background-color: #0d0d0d; border: 1px solid #252525; border-radius: 3px; min-height: 7px; }
progressbar progress { background-color: #FF6B35; border-radius: 3px; min-height: 7px; }
#footer_bar { background-color: #0a0a0a; border-top: 1px solid #222; padding: 3px 12px; min-height: 22px; }
separator { background-color: #252525; }
"""

QUALITY_LABELS = ["MP3 128", "MP3 320", "FLAC 16/44.1", "FLAC 24/96+", "Max (MQA)"]
QUALITY_VALUES = ["0",       "1",       "2",            "3",           "4"]


def detect_service_and_id(url):
    url = url.strip()
    # Qobuz standard: .../album/slug/ID
    m = re.search(r'qobuz\.com/[^/]+/album/[^/]+/([a-z0-9]+)/?', url, re.I)
    if m: return ("qobuz", m.group(1))
    # Qobuz open/share: open.qobuz.com/album/ID  ou  /albun/ID (typo réelle!)
    m = re.search(r'(?:open\.)?qobuz\.com/albu[mn]/([a-z0-9]+)/?', url, re.I)
    if m: return ("qobuz", m.group(1))
    # Deezer album
    m = re.search(r'deezer\.com/(?:[^/]+/)?album/(\d+)', url)
    if m: return ("deezer", m.group(1))
    # Deezer track
    m = re.search(r'deezer\.com/(?:[^/]+/)?track/(\d+)', url)
    if m: return ("deezer_track", m.group(1))
    # Tidal
    m = re.search(r'tidal\.com/(?:browse/)?album/(\d+)', url)
    if m: return ("tidal", m.group(1))
    if "soundcloud.com" in url: return ("soundcloud", None)
    return (None, None)


def fetch_qobuz_meta(album_id):
    """Récupère les métadonnées Qobuz via MusicBrainz (pas d'API key nécessaire)."""
    # On cherche l'album via le endpoint non-authentifié de Qobuz
    urls_to_try = [
        f"https://www.qobuz.com/api.json/0.2/album/get?album_id={album_id}&limit=50",
    ]
    for api_url in urls_to_try:
        try:
            req = urllib.request.Request(
                api_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
                    "X-App-Id":   "950096963",
                    "Origin":     "https://www.qobuz.com",
                    "Referer":    "https://www.qobuz.com/",
                }
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            if data and not data.get("status") == "error":
                return data
        except Exception:
            continue
    return None


def fetch_json(url_str):
    try:
        req = urllib.request.Request(url_str, headers={"User-Agent": "Qrip/0.1.1"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return None


def fetch_deezer_album(album_id):
    return fetch_json(f"https://api.deezer.com/album/{album_id}")


def fetch_deezer_track_album(track_id):
    data = fetch_json(f"https://api.deezer.com/track/{track_id}")
    if data:
        aid = data.get("album", {}).get("id")
        if aid:
            return fetch_deezer_album(aid)
    return None


def download_cover(cover_url, size=185):
    try:
        req = urllib.request.Request(cover_url, headers={"User-Agent": "Qrip/0.1.1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(data)
            tmp = f.name
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(tmp, size, size, True)
        os.unlink(tmp)
        return pb
    except Exception:
        return None


def resolve_config_dir() -> str:
    """
    Resolve configuration directory according to XDG_CONFIG specification.
    """
    config_home = os.getenv("XDG_CONFIG_HOME")
    if config_home is not None:
        return os.getenv("XGD_CONFIG_HOME")
    return "~/.config"


class QripApp(Gtk.Window):

    def __init__(self):
        super().__init__(title="Qrip v0.1.1")
        self.set_default_size(920, 590)
        self.set_resizable(True)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        self._process      = None
        self._dest_folder  = os.path.expanduser("~/Music")
        self._track_done   = 0
        self._total_tracks = 0
        self._build_ui()
        self.connect("destroy", self._on_quit)

    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)
        root.pack_start(self._make_header(), False, False, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(body, True, True, 0)
        body.pack_start(self._make_left(),  True,  True,  0)
        body.pack_start(self._make_right(), False, False, 0)
        root.pack_start(self._make_footer(), False, False, 0)
        self.show_all()
        self.btn_stop.hide()

    def _make_header(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bar.set_name("header_bar")
        logo = Gtk.Label()
        logo.set_markup('<span foreground="#FF6B35" size="x-large" weight="bold"> Q</span><span foreground="#ffffff" size="x-large" weight="bold">rip</span>')
        bar.pack_start(logo, False, False, 0)
        ver = Gtk.Label()
        ver.set_markup('<span foreground="#555555" size="small">v0.1.1</span>')
        ver.set_valign(Gtk.Align.END)
        ver.set_margin_bottom(3)
        bar.pack_start(ver, False, False, 0)
        for svc in ["Qobuz", "Deezer", "Tidal", "SoundCloud"]:
            l = Gtk.Label()
            l.set_markup(f'<span foreground="#3a3a3a" size="small"> {svc} </span>')
            bar.pack_start(l, False, False, 0)
        ab = Gtk.Button(label=" i ")
        ab.get_style_context().add_class("neutral-btn")
        ab.connect("clicked", self._show_about)
        bar.pack_end(ab, False, False, 0)
        return bar

    def _make_left(self):
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.set_margin_top(10); left.set_margin_bottom(10)
        left.set_margin_start(12); left.set_margin_end(8)

        lbl_url = Gtk.Label()
        lbl_url.set_markup('<span foreground="#666666" size="small">Qobuz / Deezer / Tidal / SoundCloud Link</span>')
        lbl_url.set_halign(Gtk.Align.START)
        left.pack_start(lbl_url, False, False, 0)

        self.url_entry = Gtk.Entry()
        self.url_entry.set_name("url_entry")
        self.url_entry.set_placeholder_text("https://www.qobuz.com/album/... or https://www.deezer.com/album/...")
        self.url_entry.connect("activate", self._on_download)
        left.pack_start(self.url_entry, False, False, 0)

        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        left.pack_start(row1, False, False, 0)

        qbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        qbox.set_name("quality_box")
        self._quality_checks = []
        defaults = [False, False, False, True, False]
        for i, (label, active) in enumerate(zip(QUALITY_LABELS, defaults)):
            cb = Gtk.CheckButton(label=label)
            cb.set_active(active)
            cb.connect("toggled", self._on_quality_toggled, i)
            self._quality_checks.append(cb)
            qbox.pack_start(cb, False, False, 0)
        row1.pack_start(qbox, True, True, 0)

        for label, handler in [
            ("Choose Download Folder", self._choose_folder),
            ("Open Download Folder",   self._open_folder),
            ("Open Log Folder",        self._open_log_folder),
        ]:
            btn = Gtk.Button(label=label)
            btn.get_style_context().add_class("neutral-btn")
            btn.connect("clicked", handler)
            row1.pack_start(btn, False, False, 0)

        self.folder_lbl = Gtk.Label()
        self.folder_lbl.set_markup(f'<span foreground="#404040" size="small">📁  {self._dest_folder}</span>')
        self.folder_lbl.set_halign(Gtk.Align.START)
        left.pack_start(self.folder_lbl, False, False, 0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        left.pack_start(btn_row, False, False, 0)

        self.btn_download = Gtk.Button(label="⬇   Start Download")
        self.btn_download.set_name("btn_download")
        self.btn_download.connect("clicked", self._on_download)
        btn_row.pack_start(self.btn_download, True, True, 0)

        self.btn_stop = Gtk.Button(label="⏹   Stop")
        self.btn_stop.set_name("btn_stop")
        self.btn_stop.connect("clicked", self._on_stop)
        btn_row.pack_start(self.btn_stop, False, False, 0)

        self.status_lbl = Gtk.Label()
        self.status_lbl.set_markup('<span foreground="#555555" size="small">Ready.</span>')
        self.status_lbl.set_halign(Gtk.Align.START)
        self.status_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        left.pack_start(self.status_lbl, False, False, 0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(False)
        left.pack_start(self.progress_bar, False, False, 0)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_name("log_scroll")
        self._scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.log_view = Gtk.TextView()
        self.log_view.set_name("log_view")
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        buf = self.log_view.get_buffer()
        buf.create_tag("ok",    foreground="#87a556")
        buf.create_tag("error", foreground="#e74c3c")
        buf.create_tag("track", foreground="#FF6B35")
        buf.create_tag("info",  foreground="#555555")
        buf.create_tag("dim",   foreground="#333333")
        self._scroll.add(self.log_view)
        left.pack_start(self._scroll, True, True, 0)
        return left

    def _make_right(self):
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right.set_name("right_panel")
        right.set_margin_top(10); right.set_margin_bottom(10); right.set_margin_end(10)

        self.cover_img = Gtk.Image()
        self._set_placeholder_cover()
        right.pack_start(self.cover_img, False, False, 0)

        self.cover_lbl = Gtk.Label()
        self.cover_lbl.set_markup('<span foreground="#333333" size="small">Cover Art</span>')
        right.pack_start(self.cover_lbl, False, False, 2)
        right.pack_start(Gtk.Separator(), False, False, 4)

        self._meta = {}
        for key in ["Album Artist", "Album", "Album Quality", "Total Tracks", "UPC", "Release Date"]:
            k = Gtk.Label()
            k.set_markup(f'<span foreground="#444444" size="small">{key}</span>')
            k.set_halign(Gtk.Align.START)
            right.pack_start(k, False, False, 0)
            v = Gtk.Label()
            v.set_markup('<span foreground="#666666" size="small">—</span>')
            v.set_halign(Gtk.Align.START)
            v.set_ellipsize(Pango.EllipsizeMode.END)
            v.set_max_width_chars(25)
            right.pack_start(v, False, False, 0)
            right.pack_start(Gtk.Separator(), False, False, 2)
            self._meta[key] = v
        return right

    def _make_footer(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar.set_name("footer_bar")
        self.footer_lbl = Gtk.Label()
        self.footer_lbl.set_markup('<span foreground="#333333" size="small">  Qrip v0.1.1 — Ready</span>')
        self.footer_lbl.set_halign(Gtk.Align.START)
        bar.pack_start(self.footer_lbl, True, True, 0)
        self.speed_lbl = Gtk.Label(label="")
        bar.pack_end(self.speed_lbl, False, False, 0)
        return bar

    def _set_placeholder_cover(self):
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 185, 185)
        pb.fill(0x161616ff)
        self.cover_img.set_from_pixbuf(pb)

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

    def _choose_folder(self, *_):
        dlg = Gtk.FileChooserDialog(title="Choose Download Folder", parent=self, action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            self._dest_folder = dlg.get_filename()
            self.folder_lbl.set_markup(f'<span foreground="#FF6B35" size="small">📁  {self._dest_folder}</span>')
        dlg.destroy()

    def _open_folder(self, *_):
        os.makedirs(self._dest_folder, exist_ok=True)
        subprocess.Popen(["xdg-open", self._dest_folder])

    def _open_log_folder(self, *_):
        log_dir = os.path.expanduser("~/.local/state/qrip")
        os.makedirs(log_dir, exist_ok=True)
        subprocess.Popen(["xdg-open", log_dir])

    def _on_download(self, *_):
        url = self.url_entry.get_text().strip()
        if not url:
            self._set_status("⚠   Please paste a URL first.", "error")
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
        quality = self._get_quality()
        threading.Thread(target=self._thread_main, args=(url, quality), daemon=True).start()

    def _on_stop(self, *_):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self._log("⏹   Download stopped by user.\n", "error")
            self._set_status("Stopped.", "error")
        self.btn_stop.set_sensitive(False)

    def _thread_main(self, url, quality):
        # ── Étape 1 : métadonnées API ──
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
        # ── Étape 2 : download ──
        self._run_download(url, quality)

    def _apply_deezer_meta(self, data):
        def sm(key, value):
            if value:
                txt = str(value).strip()[:28].replace("&","&amp;").replace("<","&lt;")
                self._meta[key].set_markup(f'<span foreground="#e8e8e8" size="small">{txt}</span>')
        sm("Album Artist",   data.get("artist", {}).get("name", ""))
        sm("Album",          data.get("title", ""))
        sm("Total Tracks",   data.get("nb_tracks", ""))
        sm("UPC",            data.get("upc", ""))
        sm("Release Date",   data.get("release_date", ""))
        sm("Album Quality",  "FLAC 16-bit / 44.1 kHz")
        cover_url = data.get("cover_xl") or data.get("cover_big") or data.get("cover_medium")
        if cover_url:
            threading.Thread(target=self._load_cover, args=(cover_url,), daemon=True).start()

    def _apply_qobuz_meta(self, data):
        """Métadonnées depuis l'API Qobuz."""
        def sm(key, value):
            if value:
                txt = str(value).strip()[:30].replace("&","&amp;").replace("<","&lt;")
                self._meta[key].set_markup(f'<span foreground="#e8e8e8" size="small">{txt}</span>')

        artist = data.get("artist", {}).get("name", "") or data.get("performer", {}).get("name", "")
        sm("Album Artist",  artist)
        sm("Album",         data.get("title", ""))
        sm("Total Tracks",  data.get("tracks_count", data.get("tracks", {}).get("total", "")))
        sm("UPC",           data.get("upc", ""))
        sm("Release Date",  data.get("release_date_original", data.get("released_at", ""))[:10] if data.get("release_date_original") or data.get("released_at") else "")

        # Qualité
        max_q = data.get("maximum_sampling_rate", 0)
        max_b  = data.get("maximum_bit_depth", 0)
        if max_q and max_b:
            sm("Album Quality", f"FLAC {max_b}-bit / {max_q} kHz")
        elif data.get("hires_streamable"):
            sm("Album Quality", "Hi-Res FLAC")

        # Cover — Qobuz utilise un template d'URL avec _600.jpg etc.
        img = data.get("image", {})
        cover_url = (img.get("large") or img.get("small") or img.get("thumbnail", ""))
        # Remplacer la taille pour avoir max qualité
        if cover_url:
            cover_url = re.sub(r'_\d+\.jpg', '_max.jpg', cover_url)
            cover_url_fallback = re.sub(r'_\d+\.jpg', '_600.jpg', cover_url.replace('_max.jpg', '_600.jpg'))
            threading.Thread(
                target=self._load_cover_with_fallback,
                args=(cover_url, cover_url_fallback),
                daemon=True
            ).start()

    def _load_cover_with_fallback(self, url1, url2):
        """Essaie url1 puis url2 si échec."""
        pb = download_cover(url1, size=185)
        if not pb:
            pb = download_cover(url2, size=185)
        if pb:
            GLib.idle_add(self.cover_img.set_from_pixbuf, pb)
            GLib.idle_add(self.cover_lbl.set_markup, '<span foreground="#555555" size="small">Cover Art</span>')

    def _load_cover(self, cover_url):
        pb = download_cover(cover_url, size=185)
        if pb:
            GLib.idle_add(self.cover_img.set_from_pixbuf, pb)
            GLib.idle_add(self.cover_lbl.set_markup, '<span foreground="#555555" size="small">Cover Art</span>')

    def _run_download(self, url, quality):

        cfg_path = os.path.join(resolve_config_dir(), "streamrip", "config.toml")
        cfg = os.path.expanduser(cfg_path)
        db  = os.path.expanduser("~/.config/streamrip/downloads.db")

        if os.path.exists(db):
            try:
                os.remove(db)
                GLib.idle_add(self._log, "🧹  Cache cleared.\n", "info")
            except Exception:
                pass

        if os.path.exists(cfg):
            subprocess.run(["sed", "-i", f"s/^quality = .*/quality = {quality}/", cfg], check=False)
            subprocess.run(["sed", "-i", "s/use_auth_token = .*/use_auth_token = true/", cfg], check=False)
            subprocess.run(["sed", "-i", f'0,/^folder = .*/s||folder = "{self._dest_folder}"|', cfg], check=False)

        GLib.idle_add(self._log, f"🌐  URL     : {url}\n", "info")
        GLib.idle_add(self._log, f"🎵  Quality : {quality} | Dest : {self._dest_folder}\n", "info")
        GLib.idle_add(self._log, "─" * 60 + "\n", "dim")

        # ── Trouver le chemin de rip ──
        rip_path = None
        for candidate in [
            os.path.expanduser("~/.local/bin/rip"),
            "/usr/local/bin/rip",
            "/usr/bin/rip",
        ]:
            if os.path.isfile(candidate):
                rip_path = candidate
                break

        # Chercher aussi via pipx
        if not rip_path:
            try:
                result = subprocess.run(["which", "rip"], capture_output=True, text=True)
                if result.returncode == 0:
                    rip_path = result.stdout.strip()
            except Exception:
                pass

        if not rip_path:
            GLib.idle_add(self._log,
                "❌  streamrip (rip) not found!\n"
                "    Install: pipx install streamrip\n"
                "    Then:    rip config reset\n"
                "    Also check: ls ~/.local/bin/rip\n", "error")
            GLib.idle_add(self._finish, False)
            return

        GLib.idle_add(self._log, f"🔧  Using: {rip_path}\n", "info")

        # ── Lancer via PTY (pseudo-terminal) ──
        # streamrip utilise Rich qui détecte si c'est un vrai terminal.
        # Sans pty → Rich se tait complètement → log vide.
        # Avec pty → Rich croit parler à un terminal → affiche tout.
        master_fd, slave_fd = pty.openpty()

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["TERM"] = "xterm-256color"
        env["FORCE_COLOR"] = "1"

        try:
            self._process = subprocess.Popen(
                [rip_path, "url", url],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                env=env,
            )
        except Exception as e:
            GLib.idle_add(self._log, f"❌  Could not start rip: {e}\n", "error")
            GLib.idle_add(self._finish, False)
            os.close(master_fd)
            os.close(slave_fd)
            return

        # Fermer le côté slave dans le process parent
        os.close(slave_fd)

        # Rendre master non-bloquant
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # ── Lire le pty ligne par ligne ──
        import select
        buf = ""
        while True:
            # Vérifier si le process est terminé
            if self._process.poll() is not None:
                # Vider le buffer restant
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

            # Traiter les lignes complètes
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                # Nettoyer les séquences ANSI (couleurs du terminal)
                clean = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', line)
                clean = re.sub(r'\x1b\][^\x07]*\x07', '', clean)
                clean = re.sub(r'\r', '', clean)
                if clean.strip():
                    line_out = clean + "\n"
                    GLib.idle_add(self._parse_line, line_out)

                    if re.search(r'Track Download Done', clean, re.I):
                        self._track_done += 1
                        if self._total_tracks > 0:
                            GLib.idle_add(
                                self.progress_bar.set_fraction,
                                min(self._track_done / self._total_tracks, 1.0)
                            )

                    m = re.search(r"([\d.]+\s*[KMG]B/s)", clean)
                    if m:
                        GLib.idle_add(
                            self.speed_lbl.set_markup,
                            f'<span foreground="#FF6B35" size="small">⬇  {m.group(1)}  </span>'
                        )

        try:
            os.close(master_fd)
        except Exception:
            pass

        self._process.wait()
        GLib.idle_add(self._finish, self._process.returncode == 0)

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
        elif any(w in lo for w in ["grabbing", "starting", "fetching", "found", "album", "artist", "label", "release", "quality", "tracks:"]):
            tag = "info"
        else:
            tag = None
        self._extract_meta_from_log(line)
        self._log(line, tag)

    def _extract_meta_from_log(self, line):
        """
        Patterns réels de streamrip 2.x avec Rich:
          Downloading Album Title ─────────────
          [TIME] INFO  Downloading track 'Titre'  track.py:N
          [TIME] INFO  Artist: NOM
          [TIME] INFO  Quality: FLAC 16 bit, 44.1 kHz
          [TIME] INFO  Tracks: 22
          [TIME] INFO  Release date: 2022-10-21
        """
        def sm(key, value):
            if value:
                txt = str(value).strip()[:30].replace("&","&amp;").replace("<","&lt;")
                current = self._meta[key].get_text()
                if current == "—" or not current:
                    self._meta[key].set_markup(f'<span foreground="#e8e8e8" size="small">{txt}</span>')

        # ── Format Rich: "Downloading Album Title ────────"
        # C'est le titre de l'album affiché en gros par streamrip
        m = re.search(r'^\s*Downloading\s+(.+?)\s*[─━—\-]{3,}\s*$', line)
        if m:
            title = m.group(1).strip()
            if title and not re.search(r'track|Track', title):
                sm("Album", title)

        # ── Format log: "Downloading album: Titre [id]"
        m = re.search(r'(?:Downloading|Grabbing)\s+album[:\s]+(.+?)(?:\s*\[|$)', line, re.I)
        if m: sm("Album", m.group(1))

        # ── "Downloading track 'Titre'" → titre de track courant dans status
        m = re.search(r'Downloading track\s+[\'"]?(.+?)[\'"]?(?:\s+track\.py|\s*$)', line, re.I)
        if m:
            self._set_status(f"🎵  {m.group(1).strip()[:80]}", "track")

        # ── Artist
        m = re.search(r'\bArtist[:\s]+(.+)', line, re.I)
        if m: sm("Album Artist", m.group(1).split("  ")[0].split("\t")[0])

        # ── Quality
        m = re.search(r'\bQuality[:\s]+(.+)', line, re.I)
        if m: sm("Album Quality", m.group(1).split("  ")[0])

        # ── Tracks count
        m = re.search(r'\bTracks?[:\s]+(\d+)', line, re.I)
        if m:
            count = int(m.group(1))
            if self._total_tracks == 0:
                self._total_tracks = count
            sm("Total Tracks", str(count))

        # ── Release date
        m = re.search(r'Release\s+date[:\s]+(\d{4}[-/]\d{2}[-/]\d{2})', line, re.I)
        if m: sm("Release Date", m.group(1))

        # ── UPC
        m = re.search(r'(?:UPC|Barcode)[:\s]+(\d{8,14})', line, re.I)
        if m: sm("UPC", m.group(1))

        # ── Fallback quality (détecté n'importe où dans la ligne)
        if self._meta["Album Quality"].get_text() in ("—", ""):
            for pat in [
                r'(FLAC\s+\d+\s*bit.{1,20}kHz)',
                r'(\d+\s*bit\s*/\s*[\d.]+\s*kHz)',
                r'(MP3\s+\d+\s*kbps?)',
                r'(Hi.?Res\s+FLAC)',
            ]:
                m = re.search(pat, line, re.I)
                if m: sm("Album Quality", m.group(1)); break

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
        self._set_placeholder_cover()
        self.speed_lbl.set_markup("")

    def _show_about(self, *_):
        dlg = Gtk.AboutDialog()
        dlg.set_transient_for(self)
        dlg.set_program_name("Qrip")
        dlg.set_version("v0.1.1")
        dlg.set_comments("GUI wrapper for streamrip\nQobuz • Deezer • Tidal • SoundCloud")
        dlg.set_copyright("© 2025 TheZupZup")
        dlg.set_license_type(Gtk.License.GPL_3_0)
        dlg.run()
        dlg.destroy()

    def _on_quit(self, *_):
        if self._process and self._process.poll() is None:
            self._process.terminate()
        Gtk.main_quit()


if __name__ == "__main__":
    win = QripApp()

    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
