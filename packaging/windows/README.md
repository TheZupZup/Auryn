# Windows packaging — manual `--onedir` build

This directory contains the **first** Windows packaging setup for Auryn:
a PyInstaller spec, a runtime hook for GTK3, and a PowerShell helper
script for running the build by hand on a Windows machine.

> **Status: experimental.** Windows packaging is not finished. There is no
> installer, no CI job, no code signing, and no auto-update. The only
> thing this directory currently does is let a developer produce a
> portable folder locally to smoke-test the approach.

See [`docs/windows-packaging.md`](../../docs/windows-packaging.md) for the
overall plan and the reasoning behind these choices (why `--onedir`,
why MSYS2, why streamrip stays external, etc.).

## What this produces

- A folder at `dist/Auryn/` containing `Auryn.exe` plus the bundled GTK3
  runtime, typelibs, icon themes, and Auryn's own data files.
- That folder is intended to be zipped and copied to another Windows
  machine. It runs in place; it does not need to be installed.

It does **not** produce:

- a single-file `.exe`,
- an Inno Setup / MSI installer,
- a signed binary,
- a bundled `rip.exe` or streamrip credentials.

`rip` (streamrip) remains an external dependency that the user installs
separately. Auryn discovers it via PATH at runtime.

## Build host requirements

The build must run from an **MSYS2 MINGW64** shell on Windows. A plain
pip-on-Windows environment cannot produce a working GTK3 bundle today.

Inside MSYS2, install:

```sh
pacman -S \
    mingw-w64-x86_64-gtk3 \
    mingw-w64-x86_64-python \
    mingw-w64-x86_64-python-gobject \
    mingw-w64-x86_64-python-pyinstaller
```

(`mingw-w64-x86_64-python-pyinstaller` may be installed via `pip` into
the MINGW64 Python instead, if the pacman package lags behind.)

Auryn's own Python imports — `gi`, `Gtk`, `Gdk`, `GdkPixbuf`, `Pango` —
all come from the `mingw-w64-x86_64-python-gobject` package. There is
intentionally no `requirements.txt` here yet; that is a separate cleanup.

## Running the build

From the MSYS2 MINGW64 shell, in the repo root:

```sh
# Option A: invoke PyInstaller directly.
AURYN_MINGW_PREFIX=/mingw64 pyinstaller --noconfirm --clean \
    packaging/windows/Auryn.spec

# Option B: use the PowerShell helper (from PowerShell, not bash).
pwsh -File packaging/windows/build.ps1 -Clean
```

Either way the result lands in `dist/Auryn/`. Launch `dist\Auryn\Auryn.exe`
to smoke-test.

The spec resolves the GTK runtime from `AURYN_MINGW_PREFIX` (default
`C:/msys64/mingw64`). Override it if your MSYS2 install is somewhere
else.

## What the spec ships

PyInstaller's automatic dependency analysis does **not** discover the
GTK runtime. The spec copies these explicitly out of MINGW64:

- `lib/girepository-1.0/` — typelibs for Gtk, Gdk, GLib, GObject, Gio,
  GdkPixbuf, Pango, etc.
- `lib/gdk-pixbuf-2.0/` — image loader DLLs and `loaders.cache`.
- `share/glib-2.0/schemas/` — compiled GSettings schemas.
- `share/icons/Adwaita` and `share/icons/hicolor` — icon themes.
- `share/locale/` — GLib / GTK message catalogs.
- `etc/fonts/` — Fontconfig defaults.

It also ships `src/Auryn.ui` and the SVG/PNG assets.

`runtime_hook_gtk.py` runs before Auryn's own code and points
`GI_TYPELIB_PATH`, `GDK_PIXBUF_MODULE_FILE`, `GDK_PIXBUF_MODULEDIR`,
`XDG_DATA_DIRS`, and `FONTCONFIG_PATH` at the bundled tree.

## Icon

If `assets/Auryn.ico` exists at build time the spec uses it as the
executable icon. If not, the build still succeeds — `Auryn.exe` just
gets the default PyInstaller icon. Generating a multi-resolution `.ico`
from `assets/Auryn.svg` is a separate task and is not part of this PR.

## Smoke-testing

Always test the bundle on a **clean** Windows VM with no prior GTK,
Python, or MSYS2 install. A bundle that "works" only because the
developer's machine already has GTK installed system-wide is the
classic GTK-on-Windows packaging trap.

Things to verify:

- `Auryn.exe` launches without a console error window.
- The main window appears with the dark theme and the correct icons
  (a missing gdk-pixbuf cache shows up here as missing icons).
- File pickers open without crashing.
- Status messages render with the right fonts (a broken fontconfig
  setup shows up here).
- Auryn correctly reports whether `rip.exe` is on PATH; downloads work
  if it is.

## Out of scope for this directory

- GitHub Actions / CI builds. Tracked separately.
- Inno Setup installer. Tracked separately.
- Code signing. Requires a certificate; tracked separately.
- Bundling streamrip / `rip.exe`. Intentionally not done — see
  `docs/windows-packaging.md`.
