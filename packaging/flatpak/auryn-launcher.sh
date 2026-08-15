#!/bin/sh
# Auryn launcher inside the Flatpak sandbox.
#
# Installed as /app/bin/auryn and named as the manifest's `command`.
# streamrip's own console script lives beside it at /app/bin/rip; Auryn
# resolves that path explicitly (see src/core/flatpak.py) rather than relying
# on PATH order.
exec python3 /app/share/auryn/Auryn.py "$@"
