"""Tests for the central version source of truth (``core.version``).

These guard the rule that Auryn shows one version everywhere and that GitHub
release tags (``v0.1.4``) drive the app/package version automatically, while
local and pull-request builds stay on a safe ``-dev`` version. The module is
GTK-free so these run under plain ``pytest`` without importing the application.
"""

import re

import pytest

from core import version as v


# Environment variables that influence version resolution. They are cleared
# before each test so results are deterministic regardless of where pytest
# runs (CI sets GITHUB_REF). The bake slot is reset too, in case the tests run
# against a packaged checkout where it was filled in.
_ENV_KEYS = ("AURYN_VERSION", "GITHUB_REF", "GITHUB_REF_NAME")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(v, "_BAKED_VERSION", "")


# ── normalize_release_tag ───────────────────────────────────────────────────

def test_normalize_strips_leading_v():
    assert v.normalize_release_tag("v0.1.4") == "0.1.4"


def test_normalize_passes_through_bare_version():
    assert v.normalize_release_tag("0.1.4") == "0.1.4"


def test_normalize_handles_uppercase_v_and_whitespace():
    assert v.normalize_release_tag("  V1.2  ") == "1.2"


def test_normalize_two_component_tag():
    assert v.normalize_release_tag("v0.2") == "0.2"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "v", "vv1.2", "nightly", "1.2.3-", "release-1", "1..2",
     None, 1.2],
)
def test_normalize_invalid_returns_none(bad):
    assert v.normalize_release_tag(bad) is None


# ── local / dev fallback ────────────────────────────────────────────────────

def test_dev_app_version_has_dev_suffix():
    assert v.get_app_version() == f"{v.BASE_VERSION}-{v.DEV_SUFFIX}"


def test_dev_build_version_is_base_without_suffix():
    assert v.get_build_version() == v.BASE_VERSION
    assert "dev" not in v.get_build_version()


# ── tag builds ──────────────────────────────────────────────────────────────

def test_tag_build_drives_app_and_package_version(monkeypatch):
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v0.1.4")
    monkeypatch.setenv("GITHUB_REF_NAME", "v0.1.4")
    assert v.get_app_version() == "0.1.4"
    assert v.get_build_version() == "0.1.4"


def test_tag_build_without_ref_name_falls_back_to_ref(monkeypatch):
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v2.3.4")
    assert v.get_build_version() == "2.3.4"


def test_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("AURYN_VERSION", "v9.9.9")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    assert v.get_app_version() == "9.9.9"
    assert v.get_build_version() == "9.9.9"


# ── PR / branch builds must never look like a release ───────────────────────

def test_pull_request_build_is_not_a_release(monkeypatch):
    monkeypatch.setenv("GITHUB_REF", "refs/pull/42/merge")
    monkeypatch.setenv("GITHUB_REF_NAME", "42/merge")
    assert v.get_app_version() == f"{v.BASE_VERSION}-{v.DEV_SUFFIX}"
    assert v.get_build_version() == v.BASE_VERSION


def test_branch_push_is_not_a_release(monkeypatch):
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    assert v.get_app_version().endswith(f"-{v.DEV_SUFFIX}")


# ── baked release version (installed packages, no env at runtime) ───────────

def test_baked_version_is_authoritative(monkeypatch):
    monkeypatch.setattr(v, "_BAKED_VERSION", "0.3.7")
    assert v.get_app_version() == "0.3.7"
    assert v.get_build_version() == "0.3.7"


def test_baked_version_with_leading_v_is_normalized(monkeypatch):
    monkeypatch.setattr(v, "_BAKED_VERSION", "v0.3.7")
    assert v.get_app_version() == "0.3.7"


def test_invalid_baked_version_falls_back_to_dev(monkeypatch):
    monkeypatch.setattr(v, "_BAKED_VERSION", "not-a-version!")
    assert v.get_app_version() == f"{v.BASE_VERSION}-{v.DEV_SUFFIX}"


# ── package-name safety ─────────────────────────────────────────────────────
# A version must be safe to drop into Debian/RPM/Windows artifact names.

_SAFE_PKG_RE = re.compile(r"^[0-9A-Za-z.+~-]+$")


@pytest.mark.parametrize(
    "ref",
    [None, "refs/tags/v1.2.3", "refs/heads/main", "refs/pull/9/merge"],
)
def test_build_version_is_package_safe(monkeypatch, ref):
    if ref is not None:
        monkeypatch.setenv("GITHUB_REF", ref)
        monkeypatch.setenv("GITHUB_REF_NAME", ref.rsplit("/", 1)[-1])
    bv = v.get_build_version()
    assert _SAFE_PKG_RE.match(bv), bv
    # Debian and RPM versions must begin with a digit.
    assert bv[0].isdigit()
