#!/usr/bin/env bash
# Build a noarch .rpm for Auryn using rpmbuild.
#
# Usage:
#   packaging/rpm/build-rpm.sh [VERSION]
#
# If VERSION is not provided, it is extracted from src/Auryn.py (APP_VERSION).
# The resulting .rpm is written to dist/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

VERSION="${1:-}"
if [ -z "${VERSION}" ]; then
    VERSION="$(grep -E '^APP_VERSION\s*=' src/Auryn.py | head -n1 | cut -d'"' -f2 || true)"
fi
VERSION="${VERSION:-0.0.0}"

TOPDIR="$(mktemp -d)"
trap 'rm -rf "${TOPDIR}"' EXIT
mkdir -p "${TOPDIR}"/{BUILD,BUILDROOT,RPMS,SRPMS,SPECS,SOURCES}

rpmbuild \
    --define "_topdir ${TOPDIR}" \
    --define "_sourcedir ${REPO_ROOT}" \
    --define "auryn_version ${VERSION}" \
    -bb packaging/rpm/auryn.spec

mkdir -p dist
find "${TOPDIR}/RPMS" -name '*.rpm' -print0 | xargs -0 -I{} cp {} dist/

echo "Built RPM(s):"
ls -1 dist/*.rpm
