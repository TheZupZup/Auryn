"""Single source of truth for Auryn's version.

The canonical project version is :data:`BASE_VERSION` below. Everything that
shows or records a version — the window title, the header badge, the footer,
the About dialog, ``--version`` / ``--doctor`` output, and the Debian / RPM /
Windows package metadata — derives from this module, so there is exactly one
place to bump the version for a normal source release.

Release builds never need a manual source edit. When GitHub Actions builds
from a ``v<X.Y.Z>`` tag the tag drives the version:

* the workflows resolve it (``python3 src/core/version.py --build-version`` on
  Linux, or reading ``GITHUB_REF`` directly), and
* the packaging step bakes the resolved value into :data:`_BAKED_VERSION`
  here, so the installed artifact reports the release version at runtime even
  though no GitHub environment variables exist on the user's machine.

Pull-request and ordinary ``main`` builds are never treated as releases: with
no tag they fall back to ``<BASE_VERSION>-dev`` for display.
"""

import os
import re

# ── Canonical source version ────────────────────────────────────────────────
# Bump this for a normal dev/source release. It is the only hardcoded version
# string in the project; release tags override it automatically (see below).
BASE_VERSION = "0.2.10"

# Suffix appended to BASE_VERSION for non-release (local / PR / push) builds so
# it is obvious a build did not come from a tagged GitHub Release.
DEV_SUFFIX = "dev"

# Baked at build time by the release tooling: a sed in the packaging scripts /
# workflows replaces the empty string below with the resolved tag version.
# When set to a valid version it is authoritative and used verbatim (no -dev
# suffix), so installed packages report their real release version at runtime.
_BAKED_VERSION = ""

# A package version is a small set of dotted numeric components, optionally
# followed by short alphanumeric pre-release/build segments. This is the common
# subset that is simultaneously valid for Debian, RPM and Windows artifact
# names, so any value that matches is safe to use everywhere.
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:[-.][0-9A-Za-z]+)*$")


def normalize_release_tag(tag):
    """Convert a git/release tag into a bare package version.

    Strips a single leading ``v``/``V`` plus surrounding whitespace, then
    validates the result::

        normalize_release_tag("v0.1.4")  -> "0.1.4"
        normalize_release_tag("0.1.4")   -> "0.1.4"
        normalize_release_tag("  V1.2 ") -> "1.2"

    Returns ``None`` for empty, ``None`` or syntactically invalid tags so the
    caller can fall back to a safe default.
    """
    if not tag or not isinstance(tag, str):
        return None
    tag = tag.strip()
    if tag[:1] in ("v", "V"):
        tag = tag[1:].strip()
    if not tag or not _VERSION_RE.match(tag):
        return None
    return tag


def _tag_from_env():
    """Resolve a release version from the build environment, or ``None``.

    Precedence:

    1. ``AURYN_VERSION`` — explicit override set by the release tooling.
    2. ``GITHUB_REF_NAME`` / ``GITHUB_REF`` — but only when the ref is a tag,
       so branch and pull-request builds never look like releases.
    """
    explicit = normalize_release_tag(os.environ.get("AURYN_VERSION"))
    if explicit:
        return explicit
    if os.environ.get("GITHUB_REF", "").startswith("refs/tags/"):
        ref_name = (os.environ.get("GITHUB_REF_NAME")
                    or os.environ["GITHUB_REF"].split("/", 2)[-1])
        return normalize_release_tag(ref_name)
    return None


def get_build_version():
    """Bare version for package metadata and artifact names (no leading ``v``).

    Resolution order: baked release value, then a tag in the environment, then
    :data:`BASE_VERSION`. The result is always a Debian/RPM/Windows-safe
    version string and never carries the ``-dev`` suffix.
    """
    baked = normalize_release_tag(_BAKED_VERSION)
    if baked:
        return baked
    return _tag_from_env() or BASE_VERSION


def get_app_version():
    """Version string for display (window title, footer, About, ``--version``).

    Release builds (a baked value or a tag in the environment) report the bare
    version, e.g. ``0.1.4``. Everything else reports ``<BASE_VERSION>-dev``,
    e.g. ``0.2.10-dev``, to make non-release builds obvious.
    """
    baked = normalize_release_tag(_BAKED_VERSION)
    if baked:
        return baked
    tag = _tag_from_env()
    if tag:
        return tag
    return f"{BASE_VERSION}-{DEV_SUFFIX}"


def _main(argv):
    """Tiny CLI so shell tooling resolves versions without duplicating logic.

        python3 src/core/version.py --build-version   # package/artifact version
        python3 src/core/version.py --app-version      # display version
        python3 src/core/version.py --base-version     # raw BASE_VERSION
        python3 src/core/version.py                     # same as --app-version
    """
    arg = argv[1] if len(argv) > 1 else "--app-version"
    if arg in ("--build-version", "-b"):
        print(get_build_version())
    elif arg in ("--app-version", "-a"):
        print(get_app_version())
    elif arg == "--base-version":
        print(BASE_VERSION)
    else:
        import sys
        print("usage: version.py [--build-version|--app-version|--base-version]",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv))
