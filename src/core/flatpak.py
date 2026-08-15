"""Flatpak sandbox helpers for Auryn.

Isolated, GTK-free, dependency-free logic for the third way Auryn ships,
alongside "from source / .deb / .rpm" and the packaged Windows build:

  * **Flatpak** — Auryn *and* streamrip (plus streamrip's whole Python
    dependency tree) are installed into ``/app`` inside the sandbox, so the
    user never installs Python packages or streamrip by hand. streamrip's
    console script lands at ``/app/bin/rip``.

Two things change inside the sandbox and both are handled here:

  1. **streamrip lives at a fixed path.** ``/app/bin`` is on ``PATH``, so the
     historical ``shutil.which("rip")`` lookup would find it anyway — but we
     resolve it explicitly and first, so a stale ``AURYN_STREAMRIP``
     environment variable or a leftover configured path pointing at a host
     binary (which does not exist in the sandbox) can never win.

  2. **``$HOME`` is not writable.** Flatpak gives each app a private
     per-app tree and points ``XDG_CONFIG_HOME`` / ``XDG_DATA_HOME`` /
     ``XDG_STATE_HOME`` at it (``~/.var/app/<app-id>/…``). Auryn's own
     ``~/.config/Auryn`` and ``~/.local/state/Auryn`` paths are *not*
     reachable there, so :func:`auryn_config_dir` and :func:`auryn_state_dir`
     redirect them to the sandboxed XDG locations.

     streamrip needs no such handling: it locates its own config with
     ``click.get_app_dir("streamrip")``, which already honours
     ``XDG_CONFIG_HOME``, and ``core.tidal_auth.streamrip_config_dir`` mirrors
     that exactly. Inside the sandbox both therefore resolve to
     ``~/.var/app/<app-id>/config/streamrip/config.toml`` with no environment
     variables to set and no code change to the config logic.

Everything is injectable (``environ``, ``isfile`` …) so the logic is unit
tested without a sandbox, and every helper returns ``None``/``False`` outside
Flatpak — the ``.deb``, ``.rpm``, run-from-source and Windows paths are
untouched.

Security invariant, shared with ``core.tidal_auth``: nothing here reads,
returns or logs a credential. It deals only with directory and executable
paths.
"""

import os

# Present in every Flatpak sandbox; the canonical, documented way to detect
# one from inside. Checked before $FLATPAK_ID because the file cannot be
# faked by an inherited environment variable.
FLATPAK_INFO_PATH = "/.flatpak-info"

# Auryn's Flatpak application ID. The domain portion is lowercase per the
# Flathub naming rules for code-hosting IDs (``io.github.<user>``); see
# packaging/flatpak/README.md for the full rationale.
APP_ID = "io.github.thezupzup.Auryn"

# Where the manifest installs streamrip's console script. The plain
# ``streamrip`` name is checked too so a future rename upstream does not
# silently fall through to the (absent) host lookup.
BUNDLED_STREAMRIP_CANDIDATES = ("/app/bin/rip", "/app/bin/streamrip")


def _environ(environ):
    return os.environ if environ is None else environ


def is_flatpak(environ=None, isfile=None):
    """True when this process is running inside a Flatpak sandbox."""
    _isfile = os.path.isfile if isfile is None else isfile
    try:
        if _isfile(FLATPAK_INFO_PATH):
            return True
    except OSError:
        pass
    return bool(_environ(environ).get("FLATPAK_ID"))


def app_id(environ=None, isfile=None, default=APP_ID):
    """The running app's Flatpak ID, or None when not in a sandbox.

    Falls back to :data:`APP_ID` when the sandbox does not export
    ``FLATPAK_ID`` (older flatpak releases only set ``FLATPAK_ID`` for the
    primary command), so callers always get a usable label.
    """
    if not is_flatpak(environ, isfile):
        return None
    env = _environ(environ)
    return env.get("FLATPAK_ID") or default


def get_bundled_streamrip_path(environ=None, isfile=None):
    """Resolve the streamrip bundled in the Flatpak, as an argv list.

    Returns ``["/app/bin/rip"]`` inside a Flatpak where the manifest installed
    streamrip, and ``None`` everywhere else (including inside a Flatpak whose
    build somehow omitted streamrip, so the caller can report that honestly
    instead of silently falling back to a host binary that is not there).
    """
    if not is_flatpak(environ, isfile):
        return None
    _isfile = os.path.isfile if isfile is None else isfile
    for candidate in BUNDLED_STREAMRIP_CANDIDATES:
        if _isfile(candidate):
            return [candidate]
    return None


# ── Sandboxed XDG locations ─────────────────────────────────────────────────

def _xdg_home(var, fallback_subpath, environ=None):
    """Read an XDG base-directory variable, falling back to its spec default."""
    value = (_environ(environ).get(var) or "").strip()
    if value:
        return value
    return os.path.join(os.path.expanduser("~"), *fallback_subpath)


def config_home(environ=None):
    """``$XDG_CONFIG_HOME`` (``~/.config`` by default).

    Inside Flatpak this is ``~/.var/app/<app-id>/config``.
    """
    return _xdg_home("XDG_CONFIG_HOME", (".config",), environ)


def data_home(environ=None):
    """``$XDG_DATA_HOME`` (``~/.local/share`` by default)."""
    return _xdg_home("XDG_DATA_HOME", (".local", "share"), environ)


def state_home(environ=None):
    """``$XDG_STATE_HOME`` (``~/.local/state`` by default).

    flatpak has exported ``XDG_STATE_HOME`` since 1.14. On an older host that
    leaves it unset the spec default ``~/.local/state`` would not be writable
    in the sandbox, so we fall back to a ``state/`` directory under
    ``$XDG_DATA_HOME``, which flatpak always exports and always mounts
    writable.
    """
    value = (_environ(environ).get("XDG_STATE_HOME") or "").strip()
    if value:
        return value
    env = _environ(environ)
    if (env.get("XDG_DATA_HOME") or "").strip():
        return os.path.join(env["XDG_DATA_HOME"].strip(), "state")
    return os.path.join(os.path.expanduser("~"), ".local", "state")


def auryn_config_dir(environ=None, isfile=None):
    """Auryn's own config directory inside Flatpak, or None outside it.

    ``None`` means "not in a sandbox — keep the historical path", which is
    what preserves ``~/.config/Auryn`` for source/.deb/.rpm installs.
    """
    if not is_flatpak(environ, isfile):
        return None
    return os.path.join(config_home(environ), "Auryn")


def auryn_state_dir(environ=None, isfile=None):
    """Auryn's log/state directory inside Flatpak, or None outside it."""
    if not is_flatpak(environ, isfile):
        return None
    return os.path.join(state_home(environ), "Auryn")


def streamrip_config_dir(environ=None, isfile=None):
    """streamrip's config directory inside Flatpak, or None outside it.

    Provided for diagnostics only. ``core.tidal_auth.streamrip_config_dir``
    stays the single source of truth the app actually uses; because it already
    resolves ``$XDG_CONFIG_HOME/streamrip``, it returns this same path inside
    the sandbox without needing to know Flatpak exists.
    """
    if not is_flatpak(environ, isfile):
        return None
    return os.path.join(config_home(environ), "streamrip")


# ── Diagnostics ─────────────────────────────────────────────────────────────

def describe_environment(environ=None, isfile=None):
    """Ordered ``(label, value)`` pairs describing the sandbox, for ``--doctor``.

    Returns an empty list outside Flatpak. Never includes a credential — only
    the app ID and directory/executable paths.
    """
    if not is_flatpak(environ, isfile):
        return []
    bundled = get_bundled_streamrip_path(environ, isfile)
    return [
        ("Flatpak app ID", app_id(environ, isfile) or "(unknown)"),
        ("Bundled streamrip", bundled[0] if bundled else "NOT FOUND"),
        ("streamrip config dir", streamrip_config_dir(environ, isfile)),
        ("Auryn config dir", auryn_config_dir(environ, isfile)),
        ("Auryn log dir", auryn_state_dir(environ, isfile)),
    ]
