# Packaging Auryn

Auryn ships Linux packages built by the `Linux packages` GitHub Actions
workflow (`.github/workflows/linux-packages.yml`):

- `.deb` for Debian/Ubuntu (built with `dpkg-deb`)
- `.rpm` for Fedora/openSUSE/RHEL (noarch, built with `rpmbuild`)
- Windows builds live under `packaging/windows/` (separate flow)

## streamrip is not a hard dependency

`streamrip` is **not** packaged reliably across Debian/Ubuntu, Fedora,
openSUSE, or RHEL, so neither the `.deb` nor the `.rpm` hard-depends on
it — both list it only as `Recommends:`. When Auryn starts up and the
`rip` executable is missing from `PATH`, the GUI offers to install
streamrip for the current user via `pip install --user streamrip`
(`pipx install streamrip` also works). See
`_offer_streamrip_install` in `src/Auryn.py`.

## Single source of truth for the version

The project version lives in **one** place, `src/core/version.py`:

```python
BASE_VERSION = "0.2.10"
```

Everything else derives from three small, tested helpers in that module:

- `get_app_version()` — the string shown in the UI, About dialog and
  `auryn --version` / `--doctor`. Release builds report the bare tag
  version (e.g. `0.2.10`); local/PR builds report `<BASE_VERSION>-dev`
  (e.g. `0.2.10-dev`) so a non-release build is obvious.
- `get_build_version()` — the bare version used for package metadata and
  artifact names. Never carries the `-dev` suffix and is always valid for
  Debian / RPM / Windows.
- `normalize_release_tag()` — turns a tag like `v0.1.4` into `0.1.4`
  (and rejects junk, falling back to a safe default).

`src/Auryn.py` sets `APP_VERSION = get_app_version()`; the window title,
header badge and footer are stamped at runtime, so no version string is
ever hardcoded in `Auryn.py` or `Auryn.ui`.

You should never need to edit a version string in more than one place:
bump `BASE_VERSION`, or just push a tag.

## How CI resolves the version

The `version` job in `linux-packages.yml` runs
`python3 src/core/version.py --build-version`, which:

- On a tag push matching `v*` (e.g. `v2.0.0`) → resolves to `2.0.0`
  (via `GITHUB_REF` / `GITHUB_REF_NAME`)
- On any other push / PR → resolves to `BASE_VERSION`

That value is passed to both `build-deb.sh` and `build-rpm.sh`, which:

1. Use it as the package `Version:` field, and
2. **Bake** it into `_BAKED_VERSION` in the bundled
   `usr/share/auryn/core/version.py` before packaging — so the installed
   app reports the release version at runtime even though no GitHub
   environment variables exist on the user's machine.

So a `v2.0.0` tag build produces `auryn_2.0.0_all.deb` /
`auryn-2.0.0-1.noarch.rpm`, and `auryn --version` from those packages
prints `Auryn 2.0.0` — even if `BASE_VERSION` in `main` still says
`0.2.10` at the time of the tag. The Windows workflow mirrors this and
bakes the same `_BAKED_VERSION`.

## Release flow

1. Decide the release version, e.g. `2.0.0`.
2. (Optional but recommended) Bump `BASE_VERSION` in
   `src/core/version.py`, commit, and push to `main`. This keeps the dev
   branch's `--version` honest (it will read `2.0.0-dev`).
3. Tag the commit and push the tag:

   ```sh
   git tag v2.0.0
   git push origin v2.0.0
   ```

4. The `Linux packages` workflow runs on the tag:
   - Builds `auryn_2.0.0_all.deb` and `auryn-2.0.0-1.noarch.rpm`
   - Uploads each as a workflow artifact
   - Attaches both files to the GitHub Release for `v2.0.0`
     (the Release is created if it doesn't already exist)

5. Verify:

   ```sh
   sudo dpkg -i auryn_2.0.0_all.deb     # or: sudo rpm -i auryn-2.0.0-1.noarch.rpm
   auryn --version                       # → Auryn 2.0.0
   ```

## Local builds

You don't need a tag to build locally — the scripts work on any
checkout and resolve the version from `src/core/version.py`:

```sh
packaging/debian/build-deb.sh            # uses BASE_VERSION from core.version
packaging/debian/build-deb.sh 2.0.0-dev  # explicit override

packaging/rpm/build-rpm.sh
packaging/rpm/build-rpm.sh 2.0.0-dev
```

Outputs land in `dist/`.
