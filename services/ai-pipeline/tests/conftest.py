from __future__ import annotations

import sys
from pathlib import Path


for module_name in ("analyse", "config", "main", "transcribe", "window"):
    sys.modules.pop(module_name, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
