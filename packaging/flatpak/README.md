# Auryn Flatpak

**Status: experimental.** This builds and installs locally today. Flathub
submission is deliberately *not* part of this packaging yet — see
[Before Flathub](#before-flathub) for what is still missing.

The Flatpak is the answer to the most common Auryn install problem: on
`.deb` / `.rpm` (and from source) the user still has to install streamrip
themselves via `pip` or `pipx`, and then keep a working Python environment
around. **This Flatpak bundles Auryn, streamrip, and every Python dependency
streamrip needs**, so a user runs one command and is done.

---

## The app ID

```
io.github.thezupzup.Auryn
```

The originally suggested ID was `io.github.TheZupZup.Auryn`. That one would be
**rejected by Flathub**, so this packaging uses the lowercase form.

Flathub derives code-hosting IDs from the project's GitHub Pages domain —
`thezupzup.github.io` reversed to `io.github.thezupzup` — and requires the
**domain portion of an application ID to be lowercase**. `TheZupZup` is a
display spelling of a GitHub username; GitHub usernames are case-insensitive
and the derived `github.io` hostname is always lowercased, so the domain
portion must be `io.github.thezupzup`.

Only the *domain* portion carries that rule. The final component is the
application name and may keep its capitalisation, so **`Auryn` stays
capitalised** — matching the project name, the window title and the icon
basename.

The repository must also actually exist at `github.com/thezupzup`, which it
does. Flathub's linter checks this.

Two consequences worth remembering:

- Application IDs are **case-sensitive** everywhere else in the system.
  `io.github.TheZupZup.Auryn` and `io.github.thezupzup.Auryn` are different
  applications with different data directories. Changing the ID later means
  users lose their config, so it is worth getting right before any release.
- The `.desktop` file, the AppStream metainfo file and every installed icon
  must be named after the ID exactly, or the desktop shell shows a nameless,
  icon-less entry.

---

## Runtime and SDK

```yaml
runtime: org.gnome.Platform
runtime-version: '50'
sdk: org.gnome.Sdk
```

The task suggested preferring `org.freedesktop.Platform` unless a GTK-specific
runtime is more appropriate. Here it is more appropriate:

- Auryn is a **GTK 3 + PyGObject** application.
- The GNOME runtime already ships GTK 3, `python3` and the PyGObject
  introspection bindings. Nothing extra to build.
- The freedesktop runtime ships GTK 3 but **not** PyGObject, so we would have
  to build PyGObject and pycairo from source in every build, for no gain.

This is the same choice made by other GTK 3 Python apps on Flathub.

`50` is the current GNOME runtime. **Bump `runtime-version` and the matching
`org.gnome.Sdk` together once per GNOME cycle** — Flathub rejects end-of-life
runtime branches, and GNOME 48 already went EOL in March 2026.

---

## Permissions, and why each one is there

```yaml
finish-args:
  - --share=network
  - --share=ipc
  - --socket=wayland
  - --socket=fallback-x11
  - --filesystem=xdg-music
  - --filesystem=xdg-download
```

| Permission | Why |
| --- | --- |
| `--share=network` | streamrip downloads over HTTPS; Auryn fetches cover art and lyrics. Nothing works without it. |
| `--share=ipc` | Shared memory with the display server (MIT-SHM). Conventionally paired with X11 access. |
| `--socket=wayland` | Native Wayland display. |
| `--socket=fallback-x11` | X11 **only** when there is no Wayland session — not an unconditional X11 socket. |
| `--filesystem=xdg-music` | The default download destination (`~/Music`). |
| `--filesystem=xdg-download` | The obvious second destination (`~/Downloads`). |

Deliberately **not** granted:

- `--filesystem=home` / `--filesystem=host` — Auryn would be able to read every
  file the user owns, to download music. That trade is not worth it.
- `--device=all`, `--socket=pulseaudio` — Auryn downloads music, it does not
  play it.
- `--talk-name=org.freedesktop.secrets` — credentials live in streamrip's own
  config file inside the sandbox, not in a keyring.

### Custom paths (NAS shares)

Auryn's library-organisation feature is often pointed at a NAS mount, which is
outside both granted directories. Rather than widening the manifest for
everyone, the user grants exactly the path they need:

```sh
flatpak override --user \
    --filesystem=/mnt/nas/music \
    io.github.thezupzup.Auryn
```

That keeps the default install minimal and makes the broader grant an explicit,
per-user, revocable decision (`flatpak override --user --reset io.github.thezupzup.Auryn`).

**A note on portals.** The natural alternative is to let the user pick any
folder through the file-chooser portal, which grants access to just that folder
without any static permission. Auryn currently uses `Gtk.FileChooserDialog`,
which GTK 3 does *not* route through the portal — only `GtkFileChooserNative`
is portal-backed. Inside the sandbox the dialog therefore shows exactly the
directories granted above, which is correct and safe behaviour, just not
expandable from within the dialog. Switching the chooser to
`Gtk.FileChooserNative` would enable portal-based access to arbitrary folders;
that is a UI change and is intentionally left out of this packaging-only
change. It is the natural follow-up.

---

## Where config and data live

Flatpak gives the app a private tree and points the XDG base directories at it,
so **nothing needed a special environment variable**:

| What | Path |
| --- | --- |
| streamrip config (incl. your ARL) | `~/.var/app/io.github.thezupzup.Auryn/config/streamrip/config.toml` |
| Auryn preferences | `~/.var/app/io.github.thezupzup.Auryn/config/Auryn/config.json` |
| Auryn logs | `~/.var/app/io.github.thezupzup.Auryn/.local/state/Auryn/` |
| Downloaded music | wherever you chose — `~/Music` by default, on the real host |

Why this works without configuration:

- **streamrip** locates its config with `click.get_app_dir("streamrip")`, which
  honours `$XDG_CONFIG_HOME`. Flatpak already sets that to the per-app tree.
- **Auryn** reads the same location through `core.tidal_auth.streamrip_config_dir()`,
  which resolves `$XDG_CONFIG_HOME/streamrip` too — so app and tool agree with
  no glue code.
- **Auryn's own** `~/.config/Auryn` and `~/.local/state/Auryn` *would* have
  broken, because `$HOME` is not writable in the sandbox. `core.flatpak`
  redirects those two to the sandboxed XDG locations, and only inside Flatpak —
  `.deb`, `.rpm` and from-source installs keep their historical paths exactly.

Your ARL is written only to streamrip's config file inside the sandbox. Auryn
never prints it to the log, the UI or `--doctor` output.

To confirm all of this on a running install:

```sh
flatpak run --command=auryn io.github.thezupzup.Auryn --doctor --verbose
```

which reports the app ID, the resolved bundled streamrip path, and each
sandboxed directory.

---

## Building and testing locally

### 1. Install the tooling and runtime

```sh
# Fedora
sudo dnf install flatpak flatpak-builder
# Debian / Ubuntu / Mint
sudo apt install flatpak flatpak-builder

flatpak remote-add --if-not-exists --user \
    flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user -y flathub org.gnome.Platform//50 org.gnome.Sdk//50
```

### 2. Build

From the repository root:

```sh
flatpak-builder build-dir packaging/flatpak/io.github.thezupzup.Auryn.yml --force-clean
```

The first build compiles a handful of C extensions (`aiohttp`, `Pillow`,
`pycryptodomex`, `pycares`, `cffi`) from source and takes a while. Later builds
reuse `.flatpak-builder/` and are much faster.

### 3. Install and run

```sh
flatpak-builder --user --install --force-clean \
    build-dir packaging/flatpak/io.github.thezupzup.Auryn.yml

flatpak run io.github.thezupzup.Auryn
```

### 4. Useful checks

```sh
# Diagnostics, including the sandboxed streamrip/config paths
flatpak run --command=auryn io.github.thezupzup.Auryn --doctor --verbose

# The bundled streamrip, directly
flatpak run --command=rip io.github.thezupzup.Auryn --version

# A shell inside the sandbox
flatpak run --command=sh --devel io.github.thezupzup.Auryn

# What the app is actually allowed to do
flatpak info --show-permissions io.github.thezupzup.Auryn
```

### 5. Build a distributable bundle

```sh
flatpak-builder --repo=repo --force-clean \
    build-dir packaging/flatpak/io.github.thezupzup.Auryn.yml
flatpak build-bundle repo Auryn.flatpak io.github.thezupzup.Auryn

# On the target machine:
flatpak install --user Auryn.flatpak
```

### Uninstall

```sh
flatpak uninstall --user io.github.thezupzup.Auryn
# also drop config/logs/credentials:
flatpak uninstall --user --delete-data io.github.thezupzup.Auryn
```

---

## Bundled Python dependencies

`python3-streamrip.json` pins streamrip and its entire dependency tree — 44
sources, each with an exact version and a `sha256` digest. Nothing is resolved
from the network during the build, which is both reproducible and a Flathub
requirement.

Most sources are pure-Python `py3-none-any` wheels; four (`aiohttp`, `cffi`,
`pycares`, `pycryptodomex`) are sdists compiled in the sandbox against the
GNOME SDK.

**Pillow is the exception**, and it is worth knowing why. streamrip 2.1.0 pins
`Pillow<11`, and Pillow only gained Python 3.13 *source* support in 11.0 — so
building the 10.4.0 sdist against this runtime's Python 3.13 fails on GCC 14
(`src/_webp.c`, "incompatible pointer types", now an error rather than a
warning). Pillow 10.4.0 *does* publish `cp313` manylinux wheels, so the two
prebuilt wheels are pinned instead, one per architecture via `only-arches`.
This is the same output `flatpak-pip-generator --prefer-wheels=pillow` would
produce. Once streamrip relaxes the `Pillow<11` pin, 11.x builds from sdist on
3.13 and the swap can be dropped.

Auryn itself needs no bundled Python packages at all — its only non-stdlib
import is PyGObject, which the runtime provides.

The file is generated, not hand-edited. To bump streamrip:

```sh
packaging/flatpak/generate-python-sources.sh 2.2.0
```

Then review the diff (a bump can pull in new transitive dependencies) and
rebuild.

Two quirks worth knowing when reading that file:

- streamrip 2.1.0 declares `pytest`, `pytest-mock` and `pytest-asyncio` as
  *runtime* dependencies. That is upstream's own packaging; they are bundled
  because dropping them would break the pinned `--no-index` install.
- The generator omits `packaging` by default on the grounds that
  `org.freedesktop.Sdk` ships it. That holds for the **build** environment but
  not for the `org.gnome.Platform` **runtime**, and `pytest` imports it — so
  the script passes `--ignore-installed=packaging` to bundle it anyway. The
  dependency closure is verifiably complete for linux / CPython 3.12.

---

## Before Flathub

Still to do before this can be submitted:

1. **Swap the source type.** The manifest builds the working tree
   (`type: dir`), which is what makes local and CI builds work from a checkout.
   Flathub requires a pinned `type: archive` or `type: git` source on a tagged
   release.
2. **Move the manifest to a Flathub repo.** Submission happens by PR to
   `flathub/flathub`, with the manifest named after the app ID at the repo root.
3. **Make the official linter gating.** CI already runs both lints, but
   non-gating (`continue-on-error`). The manifest lint currently reports **no
   findings**; the repo lint — the stricter of the two, checking AppStream
   completeness, the icon, screenshots and exported files — was wired up later
   and its output should be read from the latest `Flatpak` workflow run before
   submitting. Locally:
   ```sh
   flatpak run --command=flatpak-builder-lint org.flatpak.Builder \
       manifest packaging/flatpak/io.github.thezupzup.Auryn.yml
   flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo
   ```
4. **Screenshot hosting.** The metainfo points at a `raw.githubusercontent.com`
   URL, which works but should be reviewed against Flathub's screenshot
   guidance (size, and one that reflects the current UI).
5. **Version baking.** `.deb` / `.rpm` bake the release version into
   `core/version.py`; the Flatpak does not, so it reports `<BASE_VERSION>-dev`.
   That is honest for an experimental build, but a Flathub release should bake
   the tag the same way the other packages do.
6. **Decide on the file chooser.** See the portal note above.
