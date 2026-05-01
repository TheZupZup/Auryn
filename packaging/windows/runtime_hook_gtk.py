"""
PyInstaller runtime hook: point GTK3 at the bundled runtime.

Runs before Auryn's own code. GTK / GLib / GdkPixbuf look these up by
environment variable at startup, so they have to be set early — patching
them later is too late.
"""
import os
import sys


def _bundle_root() -> str:
    # In --onedir builds, sys._MEIPASS is the directory containing the
    # collected data tree. Fall back to the executable's folder for older
    # PyInstaller versions that did not set _MEIPASS for onedir.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(sys.executable))


def _set_if_exists(var: str, path: str) -> None:
    if os.path.exists(path):
        os.environ[var] = path


def _prepend_path(var: str, path: str) -> None:
    if not os.path.exists(path):
        return
    existing = os.environ.get(var, "")
    if existing:
        os.environ[var] = path + os.pathsep + existing
    else:
        os.environ[var] = path


root = _bundle_root()

# GObject introspection typelibs.
_set_if_exists("GI_TYPELIB_PATH", os.path.join(root, "lib", "girepository-1.0"))

# gdk-pixbuf loader cache. The cache file ships next to the loader DLLs.
_set_if_exists(
    "GDK_PIXBUF_MODULE_FILE",
    os.path.join(root, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders.cache"),
)
_set_if_exists(
    "GDK_PIXBUF_MODULEDIR",
    os.path.join(root, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders"),
)

# Where GTK looks for icon themes and GSettings schemas.
_prepend_path("XDG_DATA_DIRS", os.path.join(root, "share"))

# Fontconfig.
_set_if_exists("FONTCONFIG_PATH", os.path.join(root, "etc", "fonts"))

# Make the bundled MINGW64 DLLs win the search order on Windows.
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(root)
    except (OSError, FileNotFoundError):
        pass
