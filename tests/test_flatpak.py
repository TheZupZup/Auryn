"""Tests for the GTK-free Flatpak sandbox helpers (``core.flatpak``).

These guard the two behaviours the Flatpak package depends on:

  * streamrip bundled at ``/app/bin/rip`` is found first inside the sandbox,
    and
  * Auryn's own config/log directories move under the sandboxed XDG homes
    (``~/.var/app/<app-id>/…``) instead of the unwritable ``$HOME``.

Just as importantly they pin the *negative* case: outside a sandbox every
helper is inert, which is what keeps the ``.deb`` / ``.rpm`` / from-source and
Windows behaviour byte-for-byte unchanged. The module is fully injectable, so
these run under plain ``pytest`` with no Flatpak, no display and no streamrip.
"""

import os

from core import flatpak as fp


# Small helpers: a fake ``isfile`` that only knows about a fixed set of paths,
# and the two environment shapes we care about.
def only(*paths):
    known = set(paths)
    return lambda p: p in known


def nothing(_p):
    return False


SANDBOX_ENV = {
    "FLATPAK_ID": "io.github.thezupzup.Auryn",
    "XDG_CONFIG_HOME": "/home/u/.var/app/io.github.thezupzup.Auryn/config",
    "XDG_DATA_HOME": "/home/u/.var/app/io.github.thezupzup.Auryn/data",
    "XDG_STATE_HOME": "/home/u/.var/app/io.github.thezupzup.Auryn/.local/state",
}


# ── sandbox detection ───────────────────────────────────────────────────────

def test_is_flatpak_detects_flatpak_info_file():
    assert fp.is_flatpak(environ={}, isfile=only(fp.FLATPAK_INFO_PATH)) is True


def test_is_flatpak_detects_flatpak_id_env():
    assert fp.is_flatpak(environ={"FLATPAK_ID": "x"}, isfile=nothing) is True


def test_is_flatpak_false_outside_sandbox():
    assert fp.is_flatpak(environ={}, isfile=nothing) is False


def test_is_flatpak_survives_unreadable_root():
    # A sandbox-less container can raise on the /.flatpak-info probe; that must
    # degrade to the env check rather than crash the app at import time.
    def boom(_p):
        raise OSError("permission denied")

    assert fp.is_flatpak(environ={}, isfile=boom) is False
    assert fp.is_flatpak(environ={"FLATPAK_ID": "x"}, isfile=boom) is True


def test_app_id_prefers_env_and_falls_back_to_default():
    assert fp.app_id(environ=SANDBOX_ENV, isfile=nothing) == "io.github.thezupzup.Auryn"
    # In a sandbox that does not export FLATPAK_ID we still name ourselves.
    assert fp.app_id(environ={}, isfile=only(fp.FLATPAK_INFO_PATH)) == fp.APP_ID


def test_app_id_none_outside_sandbox():
    assert fp.app_id(environ={}, isfile=nothing) is None


def test_app_id_domain_part_is_lowercase():
    # Flathub requires the domain portion of a code-hosting ID to be lowercase.
    io_, github, user, _app = fp.APP_ID.split(".")
    assert (io_, github) == ("io", "github")
    assert user == user.lower()


# ── bundled streamrip ───────────────────────────────────────────────────────

def test_bundled_streamrip_found_in_sandbox():
    cmd = fp.get_bundled_streamrip_path(
        environ=SANDBOX_ENV, isfile=only("/app/bin/rip"))
    assert cmd == ["/app/bin/rip"]


def test_bundled_streamrip_accepts_alternate_name():
    cmd = fp.get_bundled_streamrip_path(
        environ=SANDBOX_ENV, isfile=only("/app/bin/streamrip"))
    assert cmd == ["/app/bin/streamrip"]


def test_bundled_streamrip_none_when_missing_from_sandbox():
    # A broken Flatpak build must report "missing" rather than silently
    # falling through to a host binary that does not exist in the sandbox.
    assert fp.get_bundled_streamrip_path(environ=SANDBOX_ENV, isfile=nothing) is None


def test_bundled_streamrip_none_outside_sandbox():
    # /app/bin/rip existing on a host (however unlikely) must not be used.
    assert fp.get_bundled_streamrip_path(
        environ={}, isfile=only("/app/bin/rip")) is None


# ── sandboxed XDG directories ───────────────────────────────────────────────

def test_config_and_state_homes_read_xdg_vars():
    assert fp.config_home(environ=SANDBOX_ENV) == SANDBOX_ENV["XDG_CONFIG_HOME"]
    assert fp.data_home(environ=SANDBOX_ENV) == SANDBOX_ENV["XDG_DATA_HOME"]
    assert fp.state_home(environ=SANDBOX_ENV) == SANDBOX_ENV["XDG_STATE_HOME"]


def test_xdg_homes_fall_back_to_spec_defaults():
    home = os.path.expanduser("~")
    assert fp.config_home(environ={}) == os.path.join(home, ".config")
    assert fp.data_home(environ={}) == os.path.join(home, ".local", "share")
    assert fp.state_home(environ={}) == os.path.join(home, ".local", "state")


def test_state_home_falls_back_under_data_home_when_unset():
    # flatpak < 1.14 does not export XDG_STATE_HOME; ~/.local/state is not
    # writable in the sandbox, so we must land under the app's data home.
    env = dict(SANDBOX_ENV)
    del env["XDG_STATE_HOME"]
    assert fp.state_home(environ=env) == os.path.join(env["XDG_DATA_HOME"], "state")


def test_auryn_dirs_are_sandboxed():
    assert fp.auryn_config_dir(environ=SANDBOX_ENV, isfile=nothing) == os.path.join(
        SANDBOX_ENV["XDG_CONFIG_HOME"], "Auryn")
    assert fp.auryn_state_dir(environ=SANDBOX_ENV, isfile=nothing) == os.path.join(
        SANDBOX_ENV["XDG_STATE_HOME"], "Auryn")


def test_streamrip_config_dir_matches_tidal_auth_inside_sandbox():
    # The app resolves streamrip's config through core.tidal_auth. Inside the
    # sandbox that must land on the same path this module reports, with no
    # environment variables set specially for streamrip.
    from core import tidal_auth

    ours = fp.streamrip_config_dir(environ=SANDBOX_ENV, isfile=nothing)
    theirs = tidal_auth.streamrip_config_dir(system="Linux", environ=SANDBOX_ENV)
    assert ours == theirs
    assert ours == os.path.join(SANDBOX_ENV["XDG_CONFIG_HOME"], "streamrip")


def test_auryn_dirs_none_outside_sandbox():
    # None is the signal that keeps ~/.config/Auryn and ~/.local/state/Auryn
    # in use for source, .deb and .rpm installs.
    assert fp.auryn_config_dir(environ={}, isfile=nothing) is None
    assert fp.auryn_state_dir(environ={}, isfile=nothing) is None
    assert fp.streamrip_config_dir(environ={}, isfile=nothing) is None


# ── diagnostics ─────────────────────────────────────────────────────────────

def test_describe_environment_empty_outside_sandbox():
    assert fp.describe_environment(environ={}, isfile=nothing) == []


def test_describe_environment_reports_paths_and_no_secrets():
    rows = fp.describe_environment(
        environ=SANDBOX_ENV, isfile=only("/app/bin/rip"))
    labels = [label for label, _ in rows]
    assert "Flatpak app ID" in labels
    assert "Bundled streamrip" in labels
    values = " ".join(str(v) for _, v in rows)
    assert "/app/bin/rip" in values
    # Diagnostics must never surface credentials or the config file contents.
    for token in ("arl", "token", "password", "config.toml"):
        assert token not in values.lower()


def test_describe_environment_flags_missing_streamrip():
    rows = dict(fp.describe_environment(environ=SANDBOX_ENV, isfile=nothing))
    assert rows["Bundled streamrip"] == "NOT FOUND"
