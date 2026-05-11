# Packaging Auryn

Auryn ships Linux packages built by the `Linux packages` GitHub Actions
workflow (`.github/workflows/linux-packages.yml`):

- `.deb` for Debian/Ubuntu (built with `dpkg-deb`)
- `.rpm` for Fedora/openSUSE/RHEL (noarch, built with `rpmbuild`)
- Windows builds live under `packaging/windows/` (separate flow)

## Single source of truth for the version

The application version is defined **once**, in `src/Auryn.py`:

```python
APP_VERSION = "0.1.1"
```

Everything else derives from it:

- `auryn --version` prints `Auryn <APP_VERSION>`
- The About dialog uses `APP_VERSION`
- `packaging/debian/build-deb.sh` and `packaging/rpm/build-rpm.sh` read
  `APP_VERSION` when no version argument is passed
- CI passes the resolved version (see below) to the build scripts, which
  then **bake** that value into the installed `Auryn.py` so the running
  app and the package metadata always match

You should never need to edit a version string in more than one place.

## How CI resolves the version

The `version` job in `linux-packages.yml`:

- On a tag push matching `v*` (e.g. `v2.0.0`) → version is `2.0.0`
- On any other push / PR → version is the current `APP_VERSION` from
  `src/Auryn.py`

That value is then passed to both `build-deb.sh` and `build-rpm.sh`,
which:

1. Use it as the package `Version:` field, and
2. Rewrite `APP_VERSION` in the bundled `usr/share/auryn/Auryn.py`
   before packaging.

So a `v2.0.0` tag build produces `auryn_2.0.0_all.deb` /
`auryn-2.0.0-1.noarch.rpm`, and `auryn --version` from those packages
prints `Auryn 2.0.0` — even if `APP_VERSION` in `main` still says
`0.1.1` at the time of the tag.

## Release flow

1. Decide the release version, e.g. `2.0.0`.
2. (Optional but recommended) Bump `APP_VERSION` in `src/Auryn.py`,
   commit, and push to `main`. This keeps the dev branch's
   `--version` honest.
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
checkout:

```sh
packaging/debian/build-deb.sh            # uses APP_VERSION from src/Auryn.py
packaging/debian/build-deb.sh 2.0.0-dev  # explicit override

packaging/rpm/build-rpm.sh
packaging/rpm/build-rpm.sh 2.0.0-dev
```

Outputs land in `dist/`.
