<p align="center">
  <img src="./assets/Auryn_256.png" width="120" alt="Auryn icon">
</p>

<h1 align="center">Auryn</h1>

<p align="center">
  <b>Build your own music library.</b><br>
  A polished, privacy-friendly desktop GUI for <a href="https://github.com/nathom/streamrip">streamrip</a> —
  download from Deezer, Qobuz, TIDAL &amp; SoundCloud straight into a
  NAS / Jellyfin / Plex-friendly folder. No terminal required.
</p>

<p align="center">
  <a href="https://github.com/TheZupZup/Auryn/actions/workflows/python-app.yml"><img src="https://github.com/TheZupZup/Auryn/actions/workflows/python-app.yml/badge.svg" alt="Python application CI"></a>
  <a href="https://github.com/TheZupZup/Auryn/actions/workflows/linux-packages.yml"><img src="https://github.com/TheZupZup/Auryn/actions/workflows/linux-packages.yml/badge.svg" alt="Linux packages"></a>
  <a href="https://github.com/TheZupZup/Auryn/releases/latest"><img src="https://img.shields.io/github/v/release/TheZupZup/Auryn?label=release" alt="Latest release"></a>
  <a href="https://www.mozilla.org/en-US/MPL/2.0/"><img src="https://img.shields.io/github/license/TheZupZup/Auryn" alt="License: MPL-2.0"></a>
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20(experimental)-2C8770" alt="Platform: Linux, experimental Windows">
</p>

<p align="center">
  <img src="./assets/Auryn_ui.png" width="900" alt="Auryn main window">
</p>

---

## What is Auryn?

Auryn is a clean, modern dark-themed graphical front-end for
[streamrip](https://github.com/nathom/streamrip), the open-source command-line
audio downloader. Its calm sea-glass jade accent keeps long download
sessions comfortable to watch. It turns streamrip's terminal workflow into a one-window
desktop app: **paste a link, pick a quality, and watch progress, metadata,
cover art, and lyrics appear as your library grows** — then drop the result
straight into Jellyfin, Plex, Symfonium, Plexamp, or any offline player.

Auryn does **not** host, distribute, or provide access to any content. It is a
GUI wrapper around a tool you install yourself — you supply your own
credentials and you are responsible for using it within the terms of the
services you access.

---

## Why Auryn?

- **No terminal needed.** Everything streamrip does from the command line —
  setup, credentials, quality, downloads — wrapped in a single window.
- **Build a library, not a download dump.** Auryn can sort finished downloads
  into a tidy `Album Artist / Album / Quality` tree (with a dedicated
  `Playlists` folder) so **Jellyfin, Plex, Symfonium and Plexamp index it
  instantly**. Point Auryn at your NAS share and you're done.
- **Privacy-friendly & local-first.** Your music lives on *your* disk or NAS.
  Auryn has no account, no telemetry, and ships no API keys — you bring your
  own service credentials, and they're stored in streamrip's own config, never
  printed to the log.
- **Honest about what works.** **Deezer is recommended** for large-catalog
  workflows, **Qobuz is best for Hi-Res** albums, and **TIDAL is experimental**
  because of upstream authentication limitations. No overpromising.
- **Rich metadata at a glance.** A protected sidebar shows cover art, album
  artist, album, quality, track count, UPC, and release date, plus a Lyrics
  tab.
- **Cross-platform.** **Linux-first**, with installable `.deb` and `.rpm`
  packages. **Windows is experimental but working**, via a self-contained build.

---

## Features

- **Deezer (recommended)** — the most reliable choice for large-catalog
  workflows, with FLAC 16/44.1 downloads.
- **Qobuz Hi-Res** — best option when you want 24-bit / Hi-Res audio.
- **TIDAL (experimental)** — supported, but authentication has known upstream
  limitations and may require manual repair/resync.
- **SoundCloud** — supported for public tracks and sets, handy for remixes and
  community uploads.
- **Library-friendly organisation** — sort downloads into
  `Album Artist / Album / Quality` folders, ready for Jellyfin / Plex /
  Symfonium / Plexamp.
- **Sequential download queue** — line up multiple URLs; they run one after
  another.
- **Metadata & cover sidebar** — artist, album, quality, track count, UPC, and
  release date alongside the album art.
- **Log, Lyrics, History, and Queue tabs** — follow live output, view synced
  lyrics, review past downloads, and manage the queue.
- **Diagnostics & setup tools** — built-in `--doctor` preflight checks plus an
  in-app Setup / Credentials / Diagnostics workflow.
- **Linux packages** — installable `.deb` and `.rpm` builds.
- **Self-contained Windows build (experimental)** — a PyInstaller bundle with
  Python, GTK and streamrip included, so no manual installs are needed (see
  [Windows notes](#windows-experimental)).

---

## Supported services

| Service | Status | Best for | Typical quality |
|---|---|---|---|
| **Deezer** | Recommended | Large catalogs, reliable downloads | FLAC 16/44.1 |
| **Qobuz** | Supported | Hi-Res albums, strong metadata | FLAC up to 24-bit |
| **TIDAL** | Experimental | — (auth may need repair/resync) | Service-dependent |
| **SoundCloud** | Supported | Public tracks, sets, remixes | Service-dependent |

> **Deezer is recommended** for large-catalog workflows. **Qobuz is best for
> Hi-Res albums.** **TIDAL is experimental** due to upstream authentication
> behaviour and may require re-authenticating through streamrip.
>
> You provide your own account credentials. Auryn ships no application IDs,
> secrets, or API keys.

---

## Installation

### Download a release

Grab the latest packages from the
[**Releases**](https://github.com/TheZupZup/Auryn/releases/latest) page.

**Debian / Ubuntu / Linux Mint (`.deb`)**

```bash
sudo dpkg -i Auryn_*.deb
sudo apt-get install -f   # pull in any missing dependencies
```

**Fedora / RHEL / openSUSE (`.rpm`)**

```bash
sudo rpm -i Auryn-*.rpm
# or: sudo dnf install ./Auryn-*.rpm
```

**Windows (experimental)**

1. Download `auryn-windows-onedir-<version>.zip` from the
   [**Releases**](https://github.com/TheZupZup/Auryn/releases/latest) page.
2. Extract it anywhere.
3. Run **`Auryn.exe`** from the extracted folder.
4. Open **Setup** and configure **Deezer** (paste your ARL).

The packaged Windows build is **self-contained** — Python, GTK and streamrip
are all bundled, so **no manual Python, pip or streamrip install is required**.
See [Windows notes](#windows-experimental) before you start.

### From source

```bash
git clone https://github.com/TheZupZup/Auryn.git
cd Auryn
python3 src/Auryn.py
```

Auryn needs **Python 3.11+**, **GTK 3 / PyGObject** (`python3-gi`,
`python3-gi-cairo`, `gir1.2-gtk-3.0`), and **streamrip** on your `PATH`. There
are no extra Python packages to `pip install` — the GUI is pure PyGObject — so
there is no `requirements.txt`; install GTK from your distro and streamrip with
`pipx`/`pip` (see [Quick start](#quick-start)).

---

## Quick start

1. **Install Auryn** — a release package (recommended) or
   [from source](#from-source).
2. **Open Setup** — click **Setup** in the top bar.
3. **Configure streamrip & credentials** — install streamrip if prompted, then
   add your service credentials (for Deezer, paste your **ARL** cookie). Auryn
   writes them to streamrip's own config.
4. **Paste a music URL** — drop a Deezer, Qobuz, TIDAL, or SoundCloud album /
   track / playlist link into the **Source URL** box.
5. **Choose a quality** — pick from MP3 320 up to FLAC 24/96+ (Auryn clamps the
   request to what the service actually supports).
6. **Download** — click **Start Download** (or **Add to Queue** to line several
   up). Watch progress, metadata, and cover art fill in.
7. **Add the folder to your player** — point **Jellyfin / Plex / Symfonium /
   Plexamp** at your download folder and enjoy your library.

> Tip: enable **"Organize downloads for music libraries"** to sort finished
> tracks into a clean `Album Artist / Album / Quality` tree that media servers
> index out of the box.

---

## How credentials & privacy work

- **streamrip is the backend.** Auryn never talks to Deezer/Qobuz/TIDAL/
  SoundCloud directly for downloads — it drives the `streamrip` CLI you install.
- **Your credentials go to streamrip, not Auryn.** When you save a Deezer ARL
  or other login in Setup, Auryn writes it to **streamrip's** `config.toml`
  (e.g. `~/.config/streamrip/config.toml`, or `%APPDATA%\streamrip\config.toml`
  on Windows) — Auryn keeps no secret store of its own.
- **No secrets in the log.** Tokens, ARLs, and passwords are never printed to
  the log panel or to `--doctor` output. `--doctor` reports only *whether*
  Deezer is configured, never the value.
- **No telemetry, no account.** Auryn doesn't phone home and has no Auryn
  account — your library stays local.

---

## Linux

Linux is Auryn's primary, best-supported platform.

- **Install** the `.deb` or `.rpm` from the
  [Releases](https://github.com/TheZupZup/Auryn/releases/latest) page (see
  [Installation](#installation)), or run
  [from source](#from-source) with system GTK.
- **Dependencies:** Python 3.11+, GTK 3 / PyGObject (`python3-gi`,
  `python3-gi-cairo`, `gir1.2-gtk-3.0`), and streamrip on your `PATH`.
- **streamrip:** install it once with `pipx install streamrip` (recommended) or
  `pip install streamrip`, then confirm with `rip --version`.
- **Self-check:** run `python3 src/Auryn.py --doctor` (add `--verbose` for
  detail) to verify Python, GTK, the `rip` executable, the streamrip config,
  and your music folder before your first download.
- The `.deb` / `.rpm` packages and the desktop entry register the Auryn icon so
  it appears in your application menu.

---

## Windows (experimental)

Windows support is **experimental but working** — and the packaged build is
**self-contained**: Python, the GTK3 runtime *and* streamrip are all bundled
inside the app. Users do **not** install Python, pip or streamrip by hand.

### Using the packaged build

1. Download `auryn-windows-onedir-<version>.zip` from a release (or CI run).
2. Extract it anywhere and run **`Auryn.exe`**.
3. On first launch Auryn offers to set up Deezer — open **Setup**, paste your
   Deezer **ARL** token, and Save. Your ARL is written only to streamrip's
   config and is never shown or logged.
4. Paste a Deezer link, pick a quality, and download.

Auryn resolves the bundled streamrip internally (it runs streamrip in its own
frozen interpreter), creates streamrip's config at
`%APPDATA%\streamrip\config.toml`, and works with no terminal steps. Run
`Auryn.exe --doctor` for a self-check that reports packaged mode, whether the
bundled streamrip was found, the config path, and whether Deezer is configured
(never the ARL itself).

> **Deezer is recommended** on Windows — a large catalog and the simplest setup
> (one ARL token). **TIDAL is experimental** and may still require manual
> re-authentication. The build is unsigned and has no installer yet.

### How it's built

The `Windows packaging (experimental)` workflow
([`.github/workflows/windows-exe.yml`](.github/workflows/windows-exe.yml)) runs
on `windows-latest`, installs GTK3 + PyGObject from MSYS2 MINGW64 **and**
`pip install`s streamrip into the same Python before PyInstaller collects
everything into the bundle. See
[docs/windows-packaging.md](docs/windows-packaging.md) for details.
Contributions toward better Windows packaging (installers, code signing) are
especially welcome.

---

## Troubleshooting

**`streamrip` / `rip` not found**
Make sure streamrip is installed and on the same `PATH` Auryn runs from. Test
with `rip --version`. If you used `pipx`, ensure `~/.local/bin` is on your
`PATH`.

**Missing `config.toml`**
streamrip creates its config on first run. Launch `rip` once, or use Auryn's
**Setup** dialog, then re-run `--doctor` to confirm the config is detected.

**"Deezer not configured"**
Deezer downloads need an ARL cookie. Open **Setup → Deezer**, paste your ARL,
and Save. Then retry the download.

**TIDAL authentication**
TIDAL is experimental. Auth tokens can expire or fail to refresh; you may need
to re-authenticate via streamrip directly. Treat TIDAL as best-effort for now.

**Windows progress looks different**
The Windows build uses a pipe-based subprocess path instead of the Linux PTY
path, so live progress output may differ slightly. Functionality is the same.

When filing an issue, the **Copy Log** button and `--doctor --verbose` output
(neither of which contains your credentials) are the most useful things to
attach.

---

## Roadmap

Auryn is actively developed. Planned and in-progress ideas — contributions
welcome:

- A smoother Windows experience (installer + optional code signing).
- More resilient TIDAL re-authentication / token repair.
- More library-layout options for different media servers.
- Quality-of-life polish: richer history, drag-and-drop URLs, more diagnostics.

This list is intentionally honest — it describes goals, not shipped features.
Have an idea? [Open an issue](https://github.com/TheZupZup/Auryn/issues).

---

## Contributing

Contributions are welcome — please keep them small and focused.

- **One change per PR.** Small, reviewable pull requests get merged faster.
- **Never push to `main`.** Branch from `main` and open a PR against it. See
  [CONTRIBUTING.md](CONTRIBUTING.md) for the full branch rules.
- **Don't change the download pipeline or break Deezer support** without
  discussion.

Run the same checks CI runs before opening a PR:

```bash
python3 -m py_compile src/Auryn.py    # syntax check
python3 -m pytest                     # unit tests (GTK-free core)
flake8 . --select=E9,F63,F7,F82       # lint for real errors
```

The test suite covers the GTK-free `core/` package, so it runs without a
display. New behaviour should come with a test where practical.

---

## Disclaimer & legal

Auryn is a graphical interface for an existing open-source audio tool. It does
not host, distribute, or provide access to copyrighted content, and it does not
directly interact with any online service. It is intended for legitimate use
with content you own or are authorized to access; users are responsible for
complying with applicable laws and the terms of service of any platform they
access.

Auryn ships no application IDs, secrets, or private API keys, and includes no
functionality for accessing restricted or protected content.

**Trademarks.** Qobuz, Deezer, TIDAL, and SoundCloud are trademarks of their
respective owners. Auryn is not affiliated with, endorsed by, or sponsored by
any of these services. Please review each platform's terms of service:
[Qobuz](https://www.qobuz.com/us-en/info/legal/terms-of-use) ·
[Deezer](https://www.deezer.com/legal/cgu) ·
[TIDAL](https://tidal.com/terms) ·
[SoundCloud](https://soundcloud.com/terms-of-use).

---

## License

Copyright © 2025 TheZupZup — Auryn
Licensed under the [Mozilla Public License Version 2.0](https://www.mozilla.org/en-US/MPL/2.0/).
