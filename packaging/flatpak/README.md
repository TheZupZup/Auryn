# Flatpak packaging (MVP)

Minimal Flatpak manifest for Auryn. **Status:** starting point — `streamrip`
is not yet bundled.

## Files

- `io.github.thezupzup.Auryn.yml` — the Flatpak manifest
- `auryn.sh` — launcher installed at `/app/bin/auryn`

## Runtime

We use `org.gnome.Platform` 45 (which is built on top of
`org.freedesktop.Platform`) because it ships GTK3, PyGObject and Python 3 out
of the box, so the manifest stays short. Switching to a pure
`org.freedesktop.Platform` base would require building GTK and PyGObject as
extra modules.

## Manifest sections explained

- `app-id` — reverse-DNS application ID. Must match the desktop file and
  icon names installed under `/app/share`.
- `runtime` / `runtime-version` / `sdk` — the platform the app runs against
  and the SDK used at build time.
- `command` — what `flatpak run` invokes; here it's the `auryn` script.
- `finish-args` — sandbox permissions: X11/Wayland for display, PulseAudio
  for sound, network for streamrip downloads, and access to
  `~/Music` / `~/Downloads` for output.
- `modules` — build steps. The single `auryn` module copies the sources to
  `/app/share/auryn`, drops a launcher in `/app/bin`, and installs the
  desktop file and icons under their app-id-prefixed names.
- The commented `python3-streamrip` block is a TODO: generate a real entry
  with `flatpak-pip-generator streamrip` and paste it above the `auryn`
  module.

## Build & test locally

From the repo root:

```sh
# 1. Install build tooling and the runtime/SDK once
flatpak install --user flathub \
    org.gnome.Platform//45 org.gnome.Sdk//45

# 2. Build into a local repo
flatpak-builder --user --force-clean \
    build-dir packaging/flatpak/io.github.thezupzup.Auryn.yml

# 3. Install the built app for the current user
flatpak-builder --user --install --force-clean \
    build-dir packaging/flatpak/io.github.thezupzup.Auryn.yml

# 4. Run it
flatpak run io.github.thezupzup.Auryn
```

For quick iteration without installing:

```sh
flatpak-builder --run build-dir \
    packaging/flatpak/io.github.thezupzup.Auryn.yml auryn
```

## Next steps

1. Run `flatpak-pip-generator streamrip` to produce
   `python3-streamrip.json`, then reference it as a module in the manifest.
2. Add an AppStream metainfo file
   (`io.github.thezupzup.Auryn.metainfo.xml`).
3. Rename `desktop/Auryn.desktop` to `io.github.thezupzup.Auryn.desktop`
   upstream so the manifest doesn't have to rename on install.
