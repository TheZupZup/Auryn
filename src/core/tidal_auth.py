"""TIDAL authentication helpers for Auryn.

Isolated, GTK-free, dependency-free logic for:

  * locating streamrip's config the same way streamrip itself does,
  * inspecting the streamrip-managed ``[tidal]`` token block,
  * validating whether the saved session looks usable or needs a re-login,
  * detecting auth / resync prompts in streamrip's output,
  * producing developer diagnostics.

Security invariant: no function in this module ever returns, logs, renders
or otherwise surfaces a raw secret value. Tokens are reported only as
"present / missing" plus a non-reversible ``sha256`` fingerprint and a
length, which is enough to debug persistence without leaking the token.

This module has no GTK / Auryn imports on purpose so it can be exercised by
``--doctor`` and unit tests without a display.
"""

import hashlib
import os
import platform
import re
import time

# Developer auth-diagnostics switch. Enabled via the environment so it can be
# turned on without code changes; the CLI also flips this at runtime when
# ``--debug-auth`` is passed.
AUTH_DEBUG = os.environ.get("AURYN_DEBUG_AUTH", "").strip().lower() in (
    "1", "true", "yes", "on",
)

# streamrip stores these TIDAL fields and manages them itself. Auryn must
# never rewrite any of them — doing so is what breaks auth persistence.
TIDAL_PROTECTED_KEYS = frozenset({
    "user_id", "country_code", "access_token", "refresh_token", "token_expiry",
})

# Same five keys, but ordered, for deterministic rewrites that match the
# pristine streamrip config template. Used *only* by clear_broken_tidal_auth
# (the single, audited exception to "never rewrite the [tidal] block").
TIDAL_AUTH_TOKEN_KEYS = (
    "user_id", "country_code", "access_token", "refresh_token", "token_expiry",
)

# streamrip refreshes a TIDAL access token when it is within one day of
# expiry (see streamrip client/tidal.py: ``token_expiry - time.time() <
# 86400``). We mirror that threshold so our diagnostics match its behaviour.
TIDAL_REFRESH_WINDOW_S = 86400


def _is_windows(system=None):
    return (system or platform.system()) == "Windows"


def streamrip_config_dir(system=None, environ=None):
    """Return streamrip's config directory.

    streamrip uses ``click.get_app_dir("streamrip")``:

      * Windows -> ``%APPDATA%\\streamrip``
      * Linux   -> ``$XDG_CONFIG_HOME/streamrip`` (default
                    ``~/.config/streamrip``)

    Parameters are injectable for testing; production callers pass nothing.
    """
    env = os.environ if environ is None else environ
    if _is_windows(system):
        base = env.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "streamrip")
    xdg = env.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(xdg, "streamrip")


def streamrip_config_path(system=None, environ=None):
    """Absolute path to streamrip's ``config.toml``."""
    return os.path.join(streamrip_config_dir(system, environ), "config.toml")


def _toml_escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def read_tidal_section(cfg_path):
    """Best-effort read of the ``[tidal]`` table from ``config.toml``.

    Returns ``{key: str}`` or ``{}`` on any problem. Never raises and never
    logs the values it reads.
    """
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    try:
        import tomllib  # stdlib on Python 3.11+

        sec = tomllib.loads(text).get("tidal")
        if isinstance(sec, dict):
            return {k: ("" if v is None else str(v)) for k, v in sec.items()}
    except Exception:
        pass
    # Regex fallback for older Pythons or a config streamrip left mid-rewrite.
    result = {}
    in_section = False
    for line in text.split("\n"):
        s = line.strip()
        m = re.match(r"\[([^\]]+)\]\s*$", s)
        if m:
            in_section = m.group(1).strip() == "tidal"
            continue
        if in_section:
            km = re.match(r'([A-Za-z0-9_]+)\s*=\s*"?(.*?)"?\s*$', s)
            if km:
                result[km.group(1)] = km.group(2)
    return result


def _present(section, key):
    v = section.get(key)
    return bool(v) and str(v).strip() not in ("", "null", "None")


def _expiry_state(raw):
    """Classify a raw token_expiry value without ever returning it.

    Returns one of ``"missing"``, ``"empty"``, ``"invalid"`` or ``"valid"``.
    ``"empty"`` and ``"invalid"`` are exactly the two states that make
    streamrip raise ``ValueError`` from ``float(token_expiry)`` and fall back
    into a re-login loop. The raw value is never logged or returned.
    """
    if raw is None:
        return "missing"
    s = str(raw).strip().strip('"').strip()
    if s in ("", "null", "None"):
        return "empty"
    try:
        float(s)
    except (TypeError, ValueError):
        return "invalid"
    return "valid"


def tidal_auth_status(cfg_path):
    """Return a structured, secret-free view of TIDAL auth state.

    Keys:
      ``config_exists``      config.toml is on disk
      ``access_present``     non-empty access_token
      ``refresh_present``    non-empty refresh_token
      ``identity_present``   non-empty user_id
      ``expiry_ts``          float epoch seconds, or None if missing/invalid
      ``expiry_problem``     human string when token_expiry is unusable
      ``expired``            True / False / None (unknown)
      ``near_expiry``        within streamrip's 1-day refresh window
      ``problems``           list of human-readable issues
      ``looks_authenticated``access+refresh+valid future expiry
      ``needs_relogin``      a fresh TIDAL setup is required to be reliable
    """
    status = {
        "config_exists": os.path.exists(cfg_path),
        "access_present": False,
        "refresh_present": False,
        "identity_present": False,
        "expiry_ts": None,
        "expiry_problem": None,
        "expired": None,
        "near_expiry": False,
        "problems": [],
        "looks_authenticated": False,
        "needs_relogin": True,
    }

    if not status["config_exists"]:
        status["problems"].append("streamrip config.toml not found.")
        return status

    sec = read_tidal_section(cfg_path)
    if not sec:
        status["problems"].append(
            "Could not read the [tidal] section from config.toml "
            "(missing or unparseable)."
        )
        return status

    status["access_present"] = _present(sec, "access_token")
    status["refresh_present"] = _present(sec, "refresh_token")
    status["identity_present"] = _present(sec, "user_id")

    raw_expiry = sec.get("token_expiry")
    if raw_expiry is None or str(raw_expiry).strip() in ("", "null", "None"):
        status["expiry_problem"] = (
            "token_expiry is empty — streamrip raises ValueError on "
            "float(\"\") and falls back to a full re-login."
        )
    else:
        try:
            status["expiry_ts"] = float(str(raw_expiry).strip().strip('"'))
        except (TypeError, ValueError):
            status["expiry_problem"] = (
                "token_expiry is not numeric — streamrip cannot load the "
                "saved session and will force a re-login."
            )

    now = time.time()
    if status["expiry_ts"] is not None:
        status["expired"] = status["expiry_ts"] <= now
        status["near_expiry"] = (
            status["expiry_ts"] - now < TIDAL_REFRESH_WINDOW_S
        )

    if not status["access_present"]:
        status["problems"].append("No TIDAL access_token saved.")
    if not status["refresh_present"]:
        status["problems"].append(
            "No TIDAL refresh_token saved — streamrip cannot refresh the "
            "session and will prompt for login again."
        )
    if status["expiry_problem"]:
        status["problems"].append(status["expiry_problem"])
    elif status["expired"]:
        status["problems"].append(
            "Saved TIDAL token has expired. streamrip refreshes it in "
            "memory but does not write the new token back, so the next "
            "download re-authenticates."
        )

    status["looks_authenticated"] = (
        status["access_present"]
        and status["refresh_present"]
        and status["expiry_ts"] is not None
        and not status["expired"]
    )
    status["needs_relogin"] = not status["looks_authenticated"]
    return status


def tidal_auth_present(cfg_path):
    """True when either a TIDAL access or refresh token is saved."""
    sec = read_tidal_section(cfg_path)
    return _present(sec, "access_token") or _present(sec, "refresh_token")


def tidal_tokens_expired(cfg_path):
    """Tri-state: True (expired/unusable), False (valid), None (unknown)."""
    st = tidal_auth_status(cfg_path)
    if not st["access_present"]:
        return True
    if st["expiry_problem"]:
        return True
    return st["expired"]


def is_tidal_url(url):
    return bool(url) and "tidal.com" in url.lower()


# Strong signals: these only appear in streamrip's TIDAL auth path.
_STRONG_AUTH_PATTERNS = (
    "access token not found",
    "refresh failed",
    "to log into tidal",
    "rip config --tidal",
    "user id mismatch",
)
# Weak signals: only treated as TIDAL auth failures when "tidal" is nearby.
_WEAK_AUTH_PATTERNS = (
    "login failed",
    "authenticationerror",
    "not authenticated",
    "could not authenticate",
    "unauthorized",
    "missing credentials",
    "missingcredentialserror",
)
_TIDAL_LOGIN_LINK_RE = re.compile(
    r"(?:link|login)\.tidal\.com|device_authorization|verificationuri", re.I
)


def detect_tidal_auth_error(text):
    """True when streamrip output indicates TIDAL auth / resync is required.

    Scoped to TIDAL so a Qobuz/Deezer error never triggers a TIDAL dialog.
    """
    if not text:
        return False
    lo = text.lower()
    if any(p in lo for p in _STRONG_AUTH_PATTERNS):
        return True
    if _TIDAL_LOGIN_LINK_RE.search(text):
        return True
    if "tidal" in lo and any(p in lo for p in _WEAK_AUTH_PATTERNS):
        return True
    return False


def detect_tidal_token_expiry_error(text):
    """True when streamrip crashed parsing an empty / corrupt token_expiry.

    This is the concrete ``ValueError: could not convert string to float:
    ''`` streamrip raises from ``float(config.session.tidal.token_expiry)``
    when the saved token_expiry is empty or non-numeric — the root cause of
    the TIDAL re-login loop.

    The ``ValueError:`` summary line rarely contains the word "tidal" (the
    streamrip file path is on a preceding traceback frame), so callers must
    keep this scoped to a TIDAL download (``is_tidal_url``) just like
    ``detect_tidal_auth_error``.
    """
    if not text:
        return False
    return "could not convert string to float" in text.lower()


def mask_secret(value):
    """Non-reversible fingerprint of a sensitive value.

    Never reveals any plaintext characters of the secret — only whether it
    is set, its length, and a short sha256 prefix so two configs can be
    compared without exposing the token.
    """
    s = "" if value is None else str(value)
    if not s:
        return "(empty)"
    digest = hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:8]
    return f"(set, len={len(s)}, sha={digest})"


def scrub_secrets(text):
    """Redact token / credential shaped substrings before display.

    Defence in depth: streamrip's device-login output does not normally
    contain tokens, but this guarantees a token can never reach the UI or
    logs. The short link.tidal.com / login.tidal.com login URL is preserved
    because it is intentionally not secret-shaped.
    """
    if not text:
        return text
    text = re.sub(
        r"(?i)\b(access_token|refresh_token|password|arl|client_secret|"
        r"app_secret|token)\b(\s*[=:]\s*)(\"?)[^\"\s\r\n]+(\"?)",
        r"\1\2\3***REDACTED***\4", text)
    text = re.sub(
        r"\beyJ[A-Za-z0-9_\-]{15,}(?:\.[A-Za-z0-9_\-]{8,}){1,2}",
        "***REDACTED***", text)
    text = re.sub(r"\b[A-Za-z0-9_\-]{48,}\b", "***REDACTED***", text)
    return text


def config_fingerprint(cfg_path):
    """Cheap, secret-free fingerprint used to detect external rewrites.

    Returns ``(exists, size, mtime_int, sha8)``. The sha is over the file
    bytes; it is only ever compared, never shown alongside contents.
    """
    try:
        with open(cfg_path, "rb") as f:
            data = f.read()
    except OSError:
        return (False, 0, 0, "")
    st = os.stat(cfg_path)
    return (True, len(data), int(st.st_mtime),
            hashlib.sha256(data).hexdigest()[:8])


def apply_streamrip_config_updates(cfg_path, edits):
    """Atomically apply scoped ``key = value`` edits to ``config.toml``.

    ``edits`` is a list of dicts: ``{"section", "key", "value", "quote"}``.
    Only an existing ``key =`` line *inside the named section* is rewritten;
    if the key is absent it is inserted directly after the section header.
    Every other section, comment and blank line is preserved verbatim and
    the file is replaced atomically with ``0600`` permissions (it can hold a
    password).

    Any edit targeting a streamrip-managed ``[tidal]`` token field is
    refused outright — this is the safety net that keeps Auryn from ever
    clobbering TIDAL auth.

    Returns ``(ok, error_or_None, changed_sections)``. Error strings never
    contain credential values.
    """
    for e in edits:
        if e["section"] == "tidal" and e["key"] in TIDAL_PROTECTED_KEYS:
            return (False,
                    "Refusing to modify streamrip-managed TIDAL auth field "
                    f"'{e['key']}'.", [])

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError as exc:
        return (False,
                f"Could not read config.toml ({exc.strerror or 'I/O error'}).",
                [])

    # Map section name -> (start_index, end_index_exclusive).
    bounds = {}
    current = None
    start = None
    for i, ln in enumerate(lines):
        m = re.match(r"\s*\[([^\]]+)\]\s*$", ln)
        if m:
            if current is not None:
                bounds[current] = (start, i)
            current = m.group(1).strip()
            start = i
    if current is not None:
        bounds[current] = (start, len(lines))

    changed = []
    # Apply in reverse section order isn't needed because inserts only shift
    # lines *after* the touched section; we recompute bounds lazily instead.
    for e in edits:
        section, key = e["section"], e["key"]
        if section not in bounds:
            # streamrip's template always has the standard sections; skip
            # unknown ones rather than inventing structure.
            continue
        s_start, s_end = bounds[section]
        if e.get("quote", True):
            rendered = f'{key} = "{_toml_escape(e["value"])}"'
        else:
            rendered = f'{key} = {e["value"]}'

        written = False
        for k in range(s_start + 1, s_end):
            km = re.match(r"\s*([A-Za-z0-9_]+)\s*=", lines[k])
            if km and km.group(1) == key:
                if lines[k] != rendered:
                    lines[k] = rendered
                    changed.append(section)
                written = True
                break
        if not written:
            lines.insert(s_start + 1, rendered)
            changed.append(section)
            # Shift every cached bound at or after the insertion point.
            for name, (a, b) in list(bounds.items()):
                na = a + 1 if a > s_start else a
                nb = b + 1 if b > s_start else b
                bounds[name] = (na, nb)

    if not changed:
        return (True, None, [])

    tmp_path = cfg_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, cfg_path)
    except OSError as exc:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return (False,
                f"Could not write config.toml ({exc.strerror or 'I/O error'}).",
                [])
    return (True, None, sorted(set(changed)))


def auth_debug_report(cfg_path):
    """Developer-friendly, fully masked TIDAL auth diagnostic block."""
    sec = read_tidal_section(cfg_path)
    st = tidal_auth_status(cfg_path)
    lines = [
        "── TIDAL auth diagnostics ─────────────────────────────",
        f"config.toml      : {cfg_path}",
        f"config exists    : {st['config_exists']}",
        f"access_token     : {mask_secret(sec.get('access_token'))}",
        f"refresh_token    : {mask_secret(sec.get('refresh_token'))}",
        f"user_id present  : {st['identity_present']}",
        f"country_code     : {'set' if _present(sec, 'country_code') else '(empty)'}",
    ]
    if st["expiry_ts"] is not None:
        when = time.strftime("%Y-%m-%d %H:%M:%S UTC",
                              time.gmtime(st["expiry_ts"]))
        delta_h = (st["expiry_ts"] - time.time()) / 3600.0
        lines.append(
            f"token_expiry     : {when} ({delta_h:+.1f} h from now)")
    else:
        lines.append("token_expiry     : (missing or non-numeric)")
    lines.append(f"expired          : {st['expired']}")
    lines.append(f"near expiry      : {st['near_expiry']}")
    lines.append(f"looks authed     : {st['looks_authenticated']}")

    v = validate_tidal_auth_state(cfg_path)
    lines.append(
        "auth fields      : access={a}, refresh={r}, user_id={u}".format(
            a="present" if v["access_present"] else "MISSING",
            r="present" if v["refresh_present"] else "MISSING",
            u="present" if v["identity_present"] else "MISSING"))
    lines.append(f"token_expiry st  : {v['expiry_state']}")
    lines.append(f"expiry parses    : {v['expiry_state'] == 'valid'}")
    lines.append(f"refresh possible : {v['refresh_possible']}")
    lines.append(f"state valid      : {v['valid']}")
    lines.append(f"auto-repairable  : {v['broken'] and v['section_readable']}")

    if st["problems"]:
        lines.append("problems         :")
        lines.extend(f"  - {p}" for p in st["problems"])
    else:
        lines.append("problems         : none")
    lines.append("───────────────────────────────────────────────────────")
    return "\n".join(lines)


def validate_tidal_auth_state(cfg_path):
    """Inspect the saved TIDAL auth block and report exactly what is broken.

    Pure inspection — never writes, never raises, never returns a secret.
    Detects the four states that send Auryn into a TIDAL re-login loop:

      * empty token_expiry        (streamrip: ``ValueError`` on ``float("")``)
      * non-numeric token_expiry  (streamrip: ``ValueError`` on ``float(...)``)
      * missing refresh_token     (streamrip cannot refresh -> re-login)
      * missing access_token      (no saved session at all)

    Returns a dict of booleans / short strings only.
    """
    result = {
        "config_exists": os.path.exists(cfg_path),
        "section_readable": False,
        "access_present": False,
        "refresh_present": False,
        "identity_present": False,
        "expiry_state": "missing",     # missing | empty | invalid | valid
        "expiry_ts": None,
        "expiry_value_error": False,   # the exact streamrip float() crash
        "refresh_possible": False,
        "broken_fields": [],
        "reasons": [],
        "valid": False,
        "broken": True,
    }

    if not result["config_exists"]:
        result["reasons"].append("streamrip config.toml not found.")
        result["broken_fields"] = list(TIDAL_AUTH_TOKEN_KEYS)
        return result

    sec = read_tidal_section(cfg_path)
    if not sec:
        result["reasons"].append(
            "Could not read the [tidal] section (missing or unparseable).")
        result["broken_fields"] = list(TIDAL_AUTH_TOKEN_KEYS)
        return result
    result["section_readable"] = True

    result["access_present"] = _present(sec, "access_token")
    result["refresh_present"] = _present(sec, "refresh_token")
    result["identity_present"] = _present(sec, "user_id")

    es = _expiry_state(sec.get("token_expiry"))
    result["expiry_state"] = es
    if es == "valid":
        try:
            result["expiry_ts"] = float(
                str(sec.get("token_expiry")).strip().strip('"'))
        except (TypeError, ValueError):
            # _expiry_state already proved this parses; defensive only.
            result["expiry_state"] = es = "invalid"
    result["expiry_value_error"] = es in ("empty", "invalid")

    if not result["access_present"]:
        result["broken_fields"].append("access_token")
        result["reasons"].append("access_token is missing.")
    if not result["refresh_present"]:
        result["broken_fields"].append("refresh_token")
        result["reasons"].append(
            "refresh_token is missing — streamrip cannot refresh the "
            "session and will prompt to log in again.")
    if es == "empty":
        result["broken_fields"].append("token_expiry")
        result["reasons"].append(
            'token_expiry is empty — streamrip raises ValueError on '
            'float("") and falls back to a full re-login.')
    elif es == "invalid":
        result["broken_fields"].append("token_expiry")
        result["reasons"].append(
            "token_expiry is not a number — streamrip raises ValueError "
            "parsing it and cannot load the saved session.")
    elif es == "missing":
        result["broken_fields"].append("token_expiry")
        result["reasons"].append("token_expiry is missing.")

    result["refresh_possible"] = (
        result["refresh_present"]
        and result["access_present"]
        and es == "valid")
    result["broken"] = bool(result["broken_fields"])
    result["valid"] = not result["broken"]
    return result


def sanitize_tidal_auth_state(cfg_path):
    """Secret-free, UI-safe summary of the TIDAL auth state + repair plan.

    Returns only presence / validity strings (never a token value) plus the
    list of fields ``clear_broken_tidal_auth`` would reset, so the same data
    can safely drive a warning dialog, the debug panel and logs without any
    chance of leaking a credential.
    """
    v = validate_tidal_auth_state(cfg_path)

    def _f(present):
        return "present" if present else "missing"

    fields = {
        "access_token": _f(v["access_present"]),
        "refresh_token": _f(v["refresh_present"]),
        "user_id": _f(v["identity_present"]),
        "token_expiry": v["expiry_state"],
    }

    if v["valid"]:
        summary = "TIDAL auth state looks complete and valid."
    elif not v["config_exists"]:
        summary = "streamrip config.toml not found — TIDAL login required."
    elif not v["section_readable"]:
        summary = ("The [tidal] section is missing or unreadable — a clean "
                   "TIDAL login is required.")
    elif v["expiry_value_error"]:
        why = ("empty" if v["expiry_state"] == "empty"
               else "not a valid number")
        summary = ("TIDAL auth data is corrupted/incomplete: token_expiry is "
                   f"{why}. streamrip would crash with a ValueError and keep "
                   "asking you to log in.")
    else:
        summary = ("TIDAL auth data is incomplete: "
                   + ", ".join(v["broken_fields"]) + " unusable.")

    return {
        "summary": summary,
        "fields": fields,
        "expiry_valid": v["expiry_state"] == "valid",
        "refresh_possible": v["refresh_possible"],
        "removable_fields": (list(TIDAL_AUTH_TOKEN_KEYS)
                             if v["broken"] else []),
        "reasons": list(v["reasons"]),
        "needs_relogin": not v["valid"],
        "can_repair": (v["config_exists"] and v["section_readable"]
                       and v["broken"]),
    }


def clear_broken_tidal_auth(cfg_path, force=False, dry_run=False):
    """Reset only the TIDAL auth token fields so a clean re-login can run.

    This is the *one* deliberate, audited exception to Auryn's rule of never
    touching streamrip's ``[tidal]`` block. It is safe because:

      * it refuses unless :func:`validate_tidal_auth_state` reports the saved
        session is actually broken (``force`` overrides for an explicit,
        user-initiated reset),
      * it only ever resets the five auth keys to ``""`` — the pristine
        streamrip-template value — and never writes a bogus value,
      * every other section, every other ``[tidal]`` key (quality,
        download_videos, …), every comment and blank line is preserved
        verbatim, and the file is replaced atomically with ``0600`` perms
        (it can hold a password).

    ``dry_run`` reports what would change without writing. Returns
    ``(ok, error_or_None, cleared_fields)``; neither the error string nor the
    field list ever contains a credential value.
    """
    v = validate_tidal_auth_state(cfg_path)
    if not v["config_exists"]:
        return (False, "streamrip config.toml not found.", [])
    if not v["broken"] and not force:
        return (False,
                "TIDAL auth state looks valid — nothing to repair.", [])

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as exc:
        return (False,
                f"Could not read config.toml ({exc.strerror or 'I/O error'}).",
                [])
    lines = raw.split("\n")

    t_start = None
    for i, ln in enumerate(lines):
        m = re.match(r"\s*\[([^\]]+)\]\s*$", ln)
        if m and m.group(1).strip() == "tidal":
            t_start = i
            break
    if t_start is None:
        return (False, "[tidal] section is missing from config.toml.", [])
    t_end = len(lines)
    for j in range(t_start + 1, len(lines)):
        if re.match(r"\s*\[([^\]]+)\]\s*$", lines[j]):
            t_end = j
            break

    cleared = []
    for k in range(t_start + 1, t_end):
        km = re.match(r"\s*([A-Za-z0-9_]+)\s*=", lines[k])
        if not km:
            continue
        key = km.group(1)
        if key in TIDAL_AUTH_TOKEN_KEYS:
            reset = f'{key} = ""'
            if lines[k] != reset:
                if not dry_run:
                    lines[k] = reset
                cleared.append(key)

    if not cleared or dry_run:
        return (True, None, sorted(set(cleared)))

    tmp_path = cfg_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, cfg_path)
    except OSError as exc:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return (False,
                f"Could not write config.toml ({exc.strerror or 'I/O error'}).",
                [])
    return (True, None, sorted(set(cleared)))


def render_auth_panel(cfg_path):
    """Compact, always-safe TIDAL auth panel for the diagnostics dialog.

    Unlike :func:`auth_debug_report` this never includes masked token
    fingerprints or file paths — only field presence, token_expiry validity
    and whether the refresh flow is possible — so it is safe to show even
    when auth-debug mode is off and never spams a raw traceback.
    """
    s = sanitize_tidal_auth_state(cfg_path)
    f = s["fields"]
    lines = [
        "── TIDAL auth state ───────────────────────────────────",
        f"summary          : {s['summary']}",
        f"access_token     : {f['access_token']}",
        f"refresh_token    : {f['refresh_token']}",
        f"user_id          : {f['user_id']}",
        f"token_expiry     : {f['token_expiry']}",
        f"token_expiry ok  : {s['expiry_valid']}",
        f"refresh possible : {s['refresh_possible']}",
        f"needs re-login   : {s['needs_relogin']}",
        f"auto-repairable  : {s['can_repair']}",
    ]
    if s["reasons"]:
        lines.append("issues           :")
        lines.extend(f"  - {r}" for r in s["reasons"])
    lines.append("───────────────────────────────────────────────────────")
    return "\n".join(lines)
