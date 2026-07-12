"""Make the showcase package importable when running pytest from this dir.

Adds ``kafka_showcase/`` (the parent of this tests/ dir) to ``sys.path`` so
``import producer`` / ``import spark_app`` resolve without an editable install.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
