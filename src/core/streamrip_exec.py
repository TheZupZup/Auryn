"""Streamrip executable resolution for Auryn.

Isolated, GTK-free, dependency-free logic for locating *and* invoking the
streamrip CLI across the two very different ways Auryn ships:

  * **Linux / from source** — streamrip is a separately installed tool. Auryn
    finds the ``rip`` command on ``PATH`` (or in the usual per-user install
    locations) and spawns it, exactly as it always has.

  * **Packaged Windows build** — the PyInstaller bundle ships streamrip and
    all of its Python dependencies *inside* the frozen application, so the end
    user never installs Python, pip or streamrip by hand. Because a relocated
    ``rip.exe`` console-script launcher cannot find the interpreter that
    created it, Auryn instead runs streamrip in its own frozen interpreter via
    a hidden multi-call entry point (``Auryn.exe --run-streamrip <args…>``).

The public resolver, :func:`get_streamrip_executable`, returns a command
**argv list** (so the multi-call form ``[sys.executable, "--run-streamrip"]``
works the same as a plain ``["/usr/bin/rip"]``) using this search order:

    1. streamrip bundled inside a packaged Windows build,
    2. an explicitly configured streamrip path, if present,
    3. the system ``PATH`` / common per-user install locations.

Every function takes injectable parameters (``frozen``, ``system``,
``environ`` …) so the logic can be unit-tested without a frozen build, a GTK
display, or streamrip actually installed. The module has no GTK / Auryn
imports on purpose, mirroring ``core.tidal_auth`` and ``core.deezer``.
"""

import importlib
import importlib.util
import os
import platform
import shutil
import sys

# argv flag that makes a packaged Auryn.exe run streamrip's CLI in-process
# instead of starting the GUI. Auryn's ``__main__`` checks for this before it
# imports GTK, so the multi-call child never opens a window.
RUN_STREAMRIP_FLAG = "--run-streamrip"


def _system(system):
    return platform.system() if system is None else system


def _environ(environ):
    return os.environ if environ is None else environ


def is_frozen(frozen=None):
    """True when running inside a PyInstaller (or similar) frozen build."""
    if frozen is not None:
        return bool(frozen)
    return bool(getattr(sys, "frozen", False))


def is_windows_packaged_build(frozen=None, system=None):
    """True when this is a packaged (frozen) Windows build of Auryn.

    This is the single switch that turns on the bundled-streamrip behaviour;
    Linux and run-from-source always return False, so their use of the system
    ``rip`` is preserved unchanged.
    """
    return is_frozen(frozen) and _system(system) == "Windows"


def bundle_root(meipass=None, executable=None):
    """Root directory of the packaged data tree (``sys._MEIPASS``).

    Falls back to the executable's directory for older PyInstaller --onedir
    builds that do not set ``_MEIPASS``.
    """
    mp = getattr(sys, "_MEIPASS", None) if meipass is None else meipass
    if mp:
        return mp
    exe = sys.executable if executable is None else executable
    return os.path.dirname(os.path.abspath(exe))


def _executable(executable=None):
    return sys.executable if executable is None else executable


def streamrip_importable(find_spec=None):
    """True when the ``streamrip`` package can be imported in this process.

    On a packaged build this is what proves streamrip was actually collected
    into the frozen interpreter, so the multi-call entry point will work.
    """
    fs = importlib.util.find_spec if find_spec is None else find_spec
    try:
        return fs("streamrip") is not None
    except Exception:
        return False


def get_bundled_streamrip_path(frozen=None, system=None, meipass=None,
                               executable=None, isfile=None, find_spec=None):
    """Resolve streamrip bundled inside a packaged Windows build.

    Returns a command argv list, or None when this is not a packaged Windows
    build or streamrip could not be found inside it. Two bundling shapes are
    supported:

      * a literal ``rip``/``streamrip`` executable shipped next to ``Auryn.exe``
        (checked first so a future self-contained ``rip.exe`` would win), and
      * streamrip collected into Auryn's own frozen interpreter, invoked via the
        ``--run-streamrip`` multi-call entry point.
    """
    if not is_windows_packaged_build(frozen, system):
        return None
    _isfile = os.path.isfile if isfile is None else isfile
    exe = _executable(executable)
    root = bundle_root(meipass, executable)
    search_dirs = [root, os.path.join(root, "_internal"),
                   os.path.dirname(os.path.abspath(exe))]
    seen = set()
    for directory in search_dirs:
        if not directory or directory in seen:
            continue
        seen.add(directory)
        for name in ("rip.exe", "streamrip.exe", "rip"):
            candidate = os.path.join(directory, name)
            if _isfile(candidate):
                return [candidate]
    # No standalone binary: run streamrip in this frozen interpreter.
    if streamrip_importable(find_spec):
        return [exe, RUN_STREAMRIP_FLAG]
    return None


def get_configured_streamrip_path(configured_path, isfile=None):
    """Return ``[path]`` when *configured_path* points at a real file, else None."""
    if not configured_path:
        return None
    _isfile = os.path.isfile if isfile is None else isfile
    path = str(configured_path).strip()
    if path and _isfile(path):
        return [path]
    return None


def find_system_streamrip(system=None, environ=None, which=None, isfile=None,
                          listdir=None, isdir=None):
    """Locate a system-installed ``rip`` on ``PATH`` or in common locations.

    This preserves Auryn's historical discovery behaviour (the body of the old
    ``_find_rip_path``) so Linux and non-packaged Windows installs keep working
    exactly as before. Returns a command argv list or None.
    """
    _which = shutil.which if which is None else which
    _isfile = os.path.isfile if isfile is None else isfile
    _listdir = os.listdir if listdir is None else listdir
    _isdir = os.path.isdir if isdir is None else isdir

    found = _which("rip")
    if found:
        return [found]

    env = _environ(environ)
    candidates = []
    if _system(system) == "Windows":
        appdata = env.get("APPDATA", "")
        localappdata = env.get("LOCALAPPDATA", "")
        userprofile = env.get("USERPROFILE", "")
        if appdata:
            candidates.append(os.path.join(appdata, "Python", "Scripts", "rip.exe"))
            candidates.append(os.path.join(
                appdata, "pipx", "venvs", "streamrip", "Scripts", "rip.exe"))
        if localappdata:
            python_root = os.path.join(localappdata, "Programs", "Python")
            try:
                if _isdir(python_root):
                    for entry in sorted(_listdir(python_root), reverse=True):
                        if entry.startswith("Python"):
                            candidates.append(os.path.join(
                                python_root, entry, "Scripts", "rip.exe"))
            except OSError:
                pass
        if userprofile:
            candidates.append(os.path.join(userprofile, ".local", "bin", "rip.exe"))
    else:
        candidates = [
            os.path.expanduser("~/.local/bin/rip"),
            "/usr/local/bin/rip",
            "/usr/bin/rip",
        ]

    for candidate in candidates:
        if _isfile(candidate):
            return [candidate]
    return None


def get_streamrip_executable(configured_path=None, frozen=None, system=None,
                             meipass=None, executable=None, isfile=None,
                             find_spec=None, which=None, environ=None,
                             listdir=None, isdir=None):
    """Resolve the streamrip command to run, as an argv list (or None).

    Search order:
        1. bundled streamrip inside a packaged Windows build,
        2. an explicitly configured streamrip path,
        3. the system PATH / common per-user install locations.
    """
    cmd = get_bundled_streamrip_path(
        frozen=frozen, system=system, meipass=meipass, executable=executable,
        isfile=isfile, find_spec=find_spec)
    if cmd:
        return cmd

    cmd = get_configured_streamrip_path(configured_path, isfile=isfile)
    if cmd:
        return cmd

    return find_system_streamrip(system=system, environ=environ, which=which,
                                 isfile=isfile, listdir=listdir, isdir=isdir)


def describe_streamrip_command(cmd):
    """Human label for a resolved streamrip command (never a secret).

    The multi-call form is reported as "bundled streamrip" rather than the
    bare ``Auryn.exe`` path so logs and diagnostics are not misleading.
    """
    if not cmd:
        return "not found"
    if len(cmd) >= 2 and cmd[1] == RUN_STREAMRIP_FLAG:
        return "bundled streamrip (packaged build)"
    return cmd[0]


# ── Multi-call dispatch (packaged Windows) ──────────────────────────────────

def _ensure_std_streams():
    """Guarantee usable ``sys.stdout``/``sys.stderr`` in a windowed frozen build.

    A PyInstaller ``console=False`` build can start with ``sys.stdout`` set to
    None. Auryn always launches the streamrip child with redirected pipes, so
    the OS file descriptors exist; rebind them defensively just in case.
    """
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, os.fdopen(fd, "w", encoding="utf-8",
                                             errors="replace", closefd=False))
            except Exception:
                pass


def _resolve_streamrip_entry():
    """Find streamrip's CLI callable across streamrip versions, or None."""
    # 1) the "rip" console_scripts entry point, if metadata was bundled.
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        try:  # Python 3.10+
            selected = list(eps.select(group="console_scripts", name="rip"))
        except AttributeError:  # Python 3.8/3.9
            selected = [e for e in eps.get("console_scripts", [])
                        if e.name == "rip"]
        for ep in selected:
            try:
                return ep.load()
            except Exception:
                continue
    except Exception:
        pass

    # 2) known module:attr locations (covers builds without dist metadata).
    for module_name, attr in (
        ("streamrip.rip.cli", "rip"),
        ("streamrip.rip.cli", "main"),
        ("streamrip.rip", "rip"),
        ("streamrip.cli", "rip"),
        ("streamrip.__main__", "rip"),
    ):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        func = getattr(module, attr, None)
        if callable(func):
            return func
    return None


def dispatch_streamrip(argv, entry=None, ensure_streams=True):
    """Run streamrip's CLI in this (frozen) interpreter and return its exit code.

    Used by the ``--run-streamrip`` multi-call path. *entry* is injectable for
    testing; production callers leave it None so the entry point is resolved
    from the bundled streamrip.
    """
    if ensure_streams:
        _ensure_std_streams()
    func = entry if entry is not None else _resolve_streamrip_entry()
    if func is None:
        sys.stderr.write(
            "Auryn: bundled streamrip entry point could not be found.\n")
        return 3
    sys.argv = ["rip"] + list(argv)
    try:
        func()
        return 0
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        sys.stderr.write(str(code) + "\n")
        return 1
