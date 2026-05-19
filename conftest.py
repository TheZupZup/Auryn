"""Pytest bootstrap: expose the GTK-free ``core`` package to tests.

Auryn's source lives under ``src/`` and adds that directory to
``sys.path`` at runtime. Mirror that here so ``from core import metadata``
resolves during ``pytest`` without importing the GTK application module.
"""

import os
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
