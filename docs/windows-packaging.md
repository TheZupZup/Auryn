# Windows Packaging Plan

This document captures the **planned** approach for distributing Auryn as a
Windows build. It is a plan, not an implementation. No build scripts, spec
files, or CI jobs are added yet — those are intentionally deferred to follow-up
PRs so the approach can be discussed before any of it is wired up.

Windows support in Auryn is currently **experimental**. Nothing in this
document promises a finished, polished Windows release.

---

## Recommended first target: portable `.zip` (PyInstaller `--onedir`)

The first Windows artifact should be a **portable zip** produced by
PyInstaller in `--onedir` mode:

- The user downloads `Auryn-windows-x64.zip`, extracts it anywhere, and runs
  `Auryn.exe` from the extracted folder.
- No installer, no registry entries, no admin rights, no auto-update.
- It is explicitly labelled as experimental and unsigned.

This is the smallest useful step that lets non-developers try Auryn on Windows
without installing Python, MSYS2, or GTK by hand.

### Why not a single `.exe` first

A single-file `.exe` (PyInstaller `--onefile` or Nuitka `--onefile`) is
tempting but is a worse first target:

- **Loader/runtime paths.** GTK3 looks up icon themes, gdk-pixbuf loaders,
  GSettings schemas, and GIR typelibs by relative path. Onefile builds extract
  to a temp directory at every launch (`sys._MEIPASS`), and the GTK loader
  caches need to be regenerated or path-patched to point inside that temp
  tree. This is the single biggest source of "works on my machine, broken on
  the user's machine" reports for GTK-on-Windows packaging.
- **SmartScreen.** Unsigned single `.exe` files trigger Windows SmartScreen
  warnings more aggressively than a folder containing many DLLs. Until we have
  code signing, `--onedir` is the friendlier default.
- **Startup cost.** Onefile extracts ~100 MB of GTK runtime at every launch.
  Onedir launches instantly.
- **Debuggability.** When something is missing from the bundle, it is much
  easier to inspect a folder than a self-extracting binary.

A single-file build can be revisited later (probably via Nuitka, which handles
GTK runtime paths more directly than PyInstaller onefile) once the onedir
build is stable.

---

## Why GTK3 / PyGObject makes Windows packaging harder

Auryn currently uses **GTK 3** via PyGObject (`gi.require_version('Gtk',
'3.0')` in `src/Auryn.py`). That choice has real consequences for Windows
packaging:

- There is **no PyPI wheel that ships GTK itself**. PyGObject wheels exist,
  but they need a working GTK runtime alongside them.
- PyInstaller's automatic dependency analysis does **not** discover the GTK
  runtime DLLs or the data trees GTK loads at runtime. Those have to be
  collected explicitly in the spec file.
- GTK theming on Windows is fragile: missing the Adwaita icon theme, the
  gdk-pixbuf `loaders.cache`, or `gschemas.compiled` produces a UI with
  missing icons or wrong fonts, but no obvious error.
- The Windows GTK3 runtime is large. Expect a bundle of roughly **90–180 MB**
  before any installer compression. There is no realistic way to make this
  small.

These constraints are inherent to GTK-on-Windows and apply to PyInstaller,
Nuitka, and any other Python bundler equally.

---

## MSYS2 / GTK3 runtime dependency notes

The supply chain we plan to rely on is **MSYS2 MINGW64**:

- Build host installs `mingw-w64-x86_64-gtk3`,
  `mingw-w64-x86_64-python`, and `mingw-w64-x86_64-python-gobject`.
- PyInstaller is run from the MSYS2 MINGW64 shell so it sees the right
  Python, the right `gi`, and the right DLL search path.
- The packaging spec copies the relevant subset of the MINGW64 runtime into
  the bundle. Roughly:
  - GTK / GLib / GObject / Gio / Pango / Cairo / GdkPixbuf / HarfBuzz /
    libepoxy / fribidi / fontconfig / freetype / pixman / png / zlib / iconv
    / intl / ffi / winpthread / gcc / stdc++ DLLs from `mingw64/bin`.
  - `lib/girepository-1.0/*.typelib` for Gtk-3.0, Gdk-3.0, GdkPixbuf-2.0,
    Gio-2.0, GLib-2.0, GObject-2.0, Pango-1.0, cairo-1.0, HarfBuzz-0.0,
    Atk-1.0.
  - `lib/gdk-pixbuf-2.0/2.10.0/loaders/` plus `loaders.cache`.
  - `share/glib-2.0/schemas/gschemas.compiled`.
  - `share/icons/Adwaita` (or hicolor) and `share/icons/hicolor/index.theme`.
- A small runtime hook sets `GI_TYPELIB_PATH`,
  `GDK_PIXBUF_MODULE_FILE`, and `XDG_DATA_DIRS` to point inside the bundled
  tree.

Note: requiring MSYS2 as a **build-time** dependency does **not** mean we ship
an MSYS2 package or ask end users to install MSYS2. End users only get the
extracted zip.

Pure pip-on-Windows (without MSYS2 or `gvsbuild`) is **not** sufficient to
produce a working GTK3 build today.

---

## streamrip / `rip.exe` stays an external dependency

We will **not** bundle streamrip or `rip.exe` inside the Windows package, at
least for now:

- streamrip moves quickly; bundling pins users to whatever version was frozen
  at release time and makes Auryn responsible for streamrip bugs we did not
  cause.
- streamrip pulls in a large transitive dependency graph (aiohttp, mutagen,
  click, the per-service API libraries, …) that would inflate the installer
  significantly.
- It keeps Auryn cleanly positioned as a graphical interface for an existing,
  separately-installed tool.
- The application already discovers `rip.exe` on Windows via PATH, pipx,
  per-user Python installs, and `~/.local/bin` (`_find_rip_path()` in
  `src/Auryn.py`).

If the missing-`rip.exe` UX needs to be friendlier (clearer error dialog,
copy-paste install command, "Recheck" button), that is a separate UX PR — not
a packaging decision.

---

## Later: optional installer via Inno Setup

Once the portable zip is stable, an installer is a reasonable next step:

- **Inno Setup** is open-source, scriptable, well documented, and integrates
  cleanly with GitHub Actions.
- The installer would wrap the same `--onedir` output, add a Start Menu
  shortcut and an uninstaller, and install per-user under
  `%LOCALAPPDATA%\Programs\Auryn` to avoid UAC prompts.
- It would still be **unsigned** until/unless code signing is funded
  separately. SmartScreen will still warn on first run.

A single-file `.exe` (Nuitka onefile) can be considered after that, only if
there is real user demand and the onedir build has proven stable.

---

## Risks and limitations

- **Bundle size.** Expect 90–180 MB. GTK3 + Python + typelibs + theme data is
  inherently large; this is not a bug we can fix.
- **GTK themes / icons.** Missing or mis-pathed Adwaita icons, gdk-pixbuf
  loader cache, or `gschemas.compiled` produces a degraded UI with no
  obvious error. This must be smoke-tested on every build.
- **SmartScreen / unsigned binaries.** Without a code-signing certificate,
  Windows will warn on first launch ("Unknown publisher"). The portable zip
  reduces but does not eliminate this. Users will need to click through.
  Document it explicitly in release notes.
- **Clean Windows VM testing is mandatory.** Builds tested only on the
  developer machine routinely "work" because the dev box already has GTK,
  fonts, and themes installed system-wide. Every release candidate must be
  launched on a fresh Windows VM with no prior GTK/Python install before it
  is published.
- **GTK3 license / runtime redistribution.** The bundled GTK3 stack is
  LGPL/GPL. Auryn is GPLv3, so this is compatible, but the bundle must ship
  the upstream license texts (a `LICENSES/` folder inside the zip) to comply
  with redistribution requirements. This applies to every Windows artifact we
  publish.
- **MSYS2 drift.** The MSYS2 GTK3 packages update frequently. We should pin
  the build to a known-good revision (or accept some reproducibility loss)
  rather than always pulling the latest.
- **Path length / OneDrive.** Deep `share/icons/...` paths can hit Windows
  `MAX_PATH` if the install root is itself deep (e.g. inside a synced
  OneDrive folder). Recommend short install roots.
- **Streamrip-on-Windows itself** is a moving target we do not control. A
  smooth Auryn install does not guarantee a smooth `rip` run.

---

## Suggested PR breakdown

Each step is a separate, reviewable PR. Earlier steps land independently of
later ones.

1. **Packaging plan doc.** *(this PR)* No code changes, no build scripts.
   Just the plan, so the approach can be reviewed before any of it is built.
2. **PyInstaller spec and local build script.** Add `packaging/windows/` with
   the `.spec` file, a runtime hook for GTK env vars, and a PowerShell or
   batch build script that runs from MSYS2 MINGW64. Manual / local use only.
3. **Windows CI artifact.** A `workflow_dispatch` GitHub Actions job on
   `windows-latest` using `msys2/setup-msys2`, running the build script and
   uploading the `--onedir` zip as a build artifact. Not yet wired to
   releases.
4. **Optional installer.** Inno Setup `.iss` script wrapping the same
   `--onedir` output, built in CI, attached to GitHub Releases as an
   experimental, unsigned installer alongside the portable zip.

A few small follow-ups are likely orthogonal to the packaging chain itself
(e.g. generating a multi-resolution `.ico` from `assets/Auryn.svg`, fixing
the README's mention of "GTK 4" in the Windows section to "GTK 3",
introducing a `requirements.txt` / `pyproject.toml`). Those can land whenever
without blocking this sequence.
