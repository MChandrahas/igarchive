"""Standalone entry point for the music backfill (KE-025). The crawler also runs
this automatically after a completed download; use this to re-probe on demand.

Usage:  .venv\\Scripts\\python.exe scripts\\backfill_music.py <username>

The logic lives in igarchive.backfill so the launcher can call it in-process.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from igarchive.backfill import backfill


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: backfill_music.py <username>")
    try:
        backfill(sys.argv[1], Path("archives"))
    except RuntimeError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
