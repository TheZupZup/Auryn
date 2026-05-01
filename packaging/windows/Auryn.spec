# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Auryn — Windows portable --onedir build.
#
# This spec is intended to be run from an MSYS2 MINGW64 shell on Windows,
# with the GTK3 runtime, PyGObject, and PyInstaller already installed there
# (see packaging/windows/README.md). It will not produce a working bundle
# from a plain pip-on-Windows environment.
#
# Output: dist/Auryn/  (a portable folder; zip it to distribute)

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# The spec is invoked from the repository root by build.ps1, so SPECPATH
# resolves to packaging/windows/. Compute REPO_ROOT relative to it.
SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent.parent
SRC_DIR = REPO_ROOT / "src"
ASSETS_DIR = REPO_ROOT / "assets"

# MSYS2 MINGW64 prefix. Override with AURYN_MINGW_PREFIX if your install
# is non-standard (e.g. C:\\msys64\\mingw64).
MINGW_PREFIX = Path(os.environ.get("AURYN_MINGW_PREFIX", "C:/msys64/mingw64"))

# ---------------------------------------------------------------------------
# Optional icon
# ---------------------------------------------------------------------------
ICON_PATH = ASSETS_DIR / "Auryn.ico"
icon_arg = str(ICON_PATH) if ICON_PATH.exists() else None

# ---------------------------------------------------------------------------
# Data files shipped from the repo
# ---------------------------------------------------------------------------
datas = [
    (str(SRC_DIR / "Auryn.ui"), "."),
    (str(ASSETS_DIR / "Auryn.svg"), "assets"),
    (str(ASSETS_DIR / "Auryn_16.png"), "assets"),
    (str(ASSETS_DIR / "Auryn_32.png"), "assets"),
    (str(ASSETS_DIR / "Auryn_48.png"), "assets"),
    (str(ASSETS_DIR / "Auryn_256.png"), "assets"),
]

# ---------------------------------------------------------------------------
# GTK3 runtime data trees from MSYS2 MINGW64
# ---------------------------------------------------------------------------
# PyInstaller's automatic analysis does NOT discover any of this. Each entry
# below is something GTK loads at runtime by relative path; missing any of
# them produces a degraded UI (missing icons, wrong fonts, blank widgets)
# without an obvious error.
gtk_data_trees = [
    # GObject introspection typelibs.
    (MINGW_PREFIX / "lib" / "girepository-1.0", "lib/girepository-1.0"),
    # gdk-pixbuf image loaders + their cache.
    (MINGW_PREFIX / "lib" / "gdk-pixbuf-2.0", "lib/gdk-pixbuf-2.0"),
    # Compiled GSettings schemas.
    (MINGW_PREFIX / "share" / "glib-2.0" / "schemas", "share/glib-2.0/schemas"),
    # Adwaita + hicolor icon themes (do not omit; Gtk falls back silently).
    (MINGW_PREFIX / "share" / "icons" / "Adwaita", "share/icons/Adwaita"),
    (MINGW_PREFIX / "share" / "icons" / "hicolor", "share/icons/hicolor"),
    # Locale data for GTK / GLib message catalogs (small but expected).
    (MINGW_PREFIX / "share" / "locale", "share/locale"),
    # Fontconfig defaults.
    (MINGW_PREFIX / "etc" / "fonts", "etc/fonts"),
]

for src, dest in gtk_data_trees:
    if src.exists():
        datas.append((str(src), dest))
    else:
        # Fail loud on the build host rather than ship a broken bundle.
        raise SystemExit(
            f"[Auryn.spec] Required GTK runtime path not found: {src}\n"
            f"Make sure mingw-w64-x86_64-gtk3 is installed and "
            f"AURYN_MINGW_PREFIX points at your MSYS2 MINGW64 root."
        )

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
# PyGObject pulls modules by name through gi; help PyInstaller find them.
hiddenimports = []
hiddenimports += collect_submodules("gi")
hiddenimports += [
    "gi",
    "gi.repository.Gtk",
    "gi.repository.Gdk",
    "gi.repository.GLib",
    "gi.repository.GObject",
    "gi.repository.Gio",
    "gi.repository.GdkPixbuf",
    "gi.repository.Pango",
]

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
a = Analysis(
    [str(SRC_DIR / "Auryn.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPEC_DIR / "runtime_hook_gtk.py")],
    excludes=[
        # Trim obvious unused stdlib pieces. Conservative; expand later if
        # bundle size becomes a real problem.
        "tkinter",
        "test",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Auryn",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Auryn",
)
