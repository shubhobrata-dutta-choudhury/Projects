"""
Root CLI Entrypoint for the Autonomous Spec-to-Code Pipeline.

Allows running commands directly without needing to set PYTHONPATH:
  python main.py benchmark --specs-dir specs --output-dir artifacts
  python main.py run specs/01_rate_limiter.json
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure `src/` is on sys.path for zero-config execution
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from spec2code.cli import main

if __name__ == "__main__":
    raise SystemExit(main())