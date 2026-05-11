#!/usr/bin/env bash
# Build a Debian/Ubuntu .deb package for Auryn using dpkg-deb.
#
# Usage:
#   packaging/debian/build-deb.sh [VERSION]
#
# If VERSION is not provided, it is extracted from src/Auryn.py (APP_VERSION).
# The resulting .deb is written to dist/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

# --- Resolve version -------------------------------------------------------
# Priority: explicit arg > APP_VERSION in src/Auryn.py > fallback.
# To bump the package version, update APP_VERSION in src/Auryn.py.
VERSION="${1:-}"
if [ -z "${VERSION}" ]; then
    VERSION="$(grep -E '^APP_VERSION\s*=' src/Auryn.py | head -n1 | cut -d'"' -f2 || true)"
fi
VERSION="${VERSION:-0.0.0}"

PKG_NAME="auryn"
ARCH="all"
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

PKG_ROOT="${STAGE}/${PKG_NAME}_${VERSION}_${ARCH}"

# --- Layout ----------------------------------------------------------------
install -d "${PKG_ROOT}/DEBIAN"
install -d "${PKG_ROOT}/usr/bin"
install -d "${PKG_ROOT}/usr/share/auryn"
install -d "${PKG_ROOT}/usr/share/auryn/core"
install -d "${PKG_ROOT}/usr/share/applications"
install -d "${PKG_ROOT}/usr/share/icons/hicolor/scalable/apps"
for size in 16 32 48 256; do
    install -d "${PKG_ROOT}/usr/share/icons/hicolor/${size}x${size}/apps"
done

# Python sources
install -m 0644 src/Auryn.py "${PKG_ROOT}/usr/share/auryn/Auryn.py"
# Bake the resolved version into the installed Auryn.py so that
# `auryn --version` and the About dialog report the same version as the
# package metadata (especially on tag builds where VERSION comes from the tag).
sed -i -E "s|^APP_VERSION\s*=.*|APP_VERSION = \"${VERSION}\"|" \
    "${PKG_ROOT}/usr/share/auryn/Auryn.py"
install -m 0644 src/Auryn.ui "${PKG_ROOT}/usr/share/auryn/Auryn.ui"
install -m 0644 src/core/__init__.py "${PKG_ROOT}/usr/share/auryn/core/__init__.py"
install -m 0644 src/core/errors.py "${PKG_ROOT}/usr/share/auryn/core/errors.py"
install -m 0644 src/core/status.py "${PKG_ROOT}/usr/share/auryn/core/status.py"

# Desktop entry (already present in repo)
install -m 0644 desktop/Auryn.desktop "${PKG_ROOT}/usr/share/applications/Auryn.desktop"

# Icons
install -m 0644 assets/Auryn.svg "${PKG_ROOT}/usr/share/icons/hicolor/scalable/apps/Auryn.svg"
for size in 16 32 48 256; do
    install -m 0644 "assets/Auryn_${size}.png" \
        "${PKG_ROOT}/usr/share/icons/hicolor/${size}x${size}/apps/Auryn.png"
done

# Launcher: /usr/bin/Auryn -> python3 /usr/share/auryn/Auryn.py
# Named "Auryn" (capital A) to match the existing desktop entry's Exec=Auryn.
# A lowercase "auryn" symlink is provided as a convenience for shells.
cat > "${PKG_ROOT}/usr/bin/Auryn" <<'EOF'
#!/bin/sh
exec python3 /usr/share/auryn/Auryn.py "$@"
EOF
chmod 0755 "${PKG_ROOT}/usr/bin/Auryn"
ln -s Auryn "${PKG_ROOT}/usr/bin/auryn"

# --- Control file ----------------------------------------------------------
# streamrip is not reliably packaged in Debian/Ubuntu archives. We keep it as
# a "Recommends" only and document the pip/pipx fallback; Auryn itself
# detects a missing 'rip' at runtime and offers to install it.
cat > "${PKG_ROOT}/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: ${ARCH}
Depends: python3, python3-gi, gir1.2-gtk-3.0
Recommends: streamrip
Maintainer: TheZupZup <noreply@github.com>
Homepage: https://github.com/thezupzup/auryn
Description: GTK GUI for streamrip
 Auryn is a simple GTK 3 graphical front-end for the streamrip
 command-line music downloader. If the 'streamrip' package is not
 available on your distribution, install it with:
 .
   pipx install streamrip
EOF

# --- Build -----------------------------------------------------------------
mkdir -p dist
OUT="dist/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "${PKG_ROOT}" "${OUT}"

echo "Built: ${OUT}"
