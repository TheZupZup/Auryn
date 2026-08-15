#!/usr/bin/env bash
# Regenerate packaging/flatpak/python3-streamrip.json.
#
# The Flatpak bundles streamrip and its whole Python dependency tree. Flathub
# (and reproducible builds generally) require every source to be pinned to an
# exact version with a sha256 digest instead of letting pip resolve packages
# from the network during the build, so the module file is *generated* by
# upstream's flatpak-pip-generator and committed.
#
# Usage:
#   packaging/flatpak/generate-python-sources.sh            # pinned version below
#   packaging/flatpak/generate-python-sources.sh 2.2.0      # bump streamrip
#
# Requires network access and python3. Review the resulting diff before
# committing: a bump can pull in new transitive dependencies.

set -euo pipefail

# The streamrip release the Flatpak ships. Bump here, re-run, commit both this
# file and the regenerated python3-streamrip.json together.
STREAMRIP_VERSION="${1:-2.1.0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GENERATOR_URL="https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/master/pip/flatpak-pip-generator.py"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "==> Fetching flatpak-pip-generator"
curl -sSfL "${GENERATOR_URL}" -o "${WORK}/flatpak-pip-generator.py"

echo "==> Preparing an isolated environment for the generator"
python3 -m venv "${WORK}/venv"
"${WORK}/venv/bin/pip" install --quiet --upgrade \
    pip setuptools wheel requirements-parser packaging

echo "==> Generating pinned sources for streamrip==${STREAMRIP_VERSION}"
# Run from the work dir so the generator's output lands there, then move it
# into place only on success.
(
    cd "${WORK}"
    # --ignore-installed=packaging: the generator skips `packaging` by default
    # because org.freedesktop.Sdk ships it, which is true of the *build*
    # environment but not of the org.gnome.Platform *runtime*. streamrip pulls
    # pytest in as a runtime dependency (upstream's own packaging quirk) and
    # pytest imports `packaging`, so bundle it explicitly rather than rely on
    # nothing ever importing it at runtime.
    ./venv/bin/python flatpak-pip-generator.py \
        --output python3-streamrip \
        --ignore-installed=packaging \
        "streamrip==${STREAMRIP_VERSION}"
)

# Normalise the indentation so future diffs stay reviewable.
python3 - "${WORK}/python3-streamrip.json" "${SCRIPT_DIR}/python3-streamrip.json" <<'PY'
import json
import sys

src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as f:
    data = json.load(f)
with open(dst, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4)
    f.write("\n")
PY

count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["sources"]))' \
    "${SCRIPT_DIR}/python3-streamrip.json")"

echo "==> Wrote ${SCRIPT_DIR}/python3-streamrip.json (${count} pinned sources)"
echo "    Review the diff, then rebuild the Flatpak to verify."
