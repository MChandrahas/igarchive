"""Streaming bytes to disk + ffmpeg audio extraction. Never decodes media (D-004).

No image library imports here, ever — opening a JPEG and re-saving it silently
destroys quality (KE-013). ffmpeg runs with stream-copy only (KE-014).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx
import structlog

log = structlog.get_logger(__name__)


def download(client: httpx.Client, url: str, dest: Path, taken_at: datetime | None) -> None:
    """Stream a URL to disk byte-for-byte and restore mtime to the post date."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    if taken_at is not None:
        ts = taken_at.timestamp()
        os.utime(dest, (ts, ts))
    log.info("media_downloaded", dest=str(dest), bytes=dest.stat().st_size)


def ffmpeg_path() -> str | None:
    """Locate ffmpeg: bundled next to the PyInstaller payload first (KE-022), then PATH,
    then the winget shim dir (present when the install postdates the parent shell's PATH)."""
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    if hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / exe
        if bundled.exists():
            return str(bundled)
    found = shutil.which("ffmpeg")
    if found:
        return found
    if sys.platform == "win32":
        winget = Path.home() / "AppData/Local/Microsoft/WinGet/Links" / exe
        if winget.exists():
            return str(winget)
    return None


def extract_audio(mp4: Path, m4a: Path) -> bool:
    """Stream-copy the audio track out of a reel mp4. Bit-identical, never transcodes."""
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        log.warning("ffmpeg_missing", skipped=str(m4a))
        return False
    result = subprocess.run(
        [ffmpeg, "-i", str(mp4), "-vn", "-acodec", "copy", "-y", str(m4a)],
        capture_output=True,
    )
    if result.returncode != 0 or not m4a.exists():
        log.warning(
            "audio_extract_failed",
            mp4=str(mp4),
            stderr=result.stderr[-500:].decode(errors="replace"),
        )
        return False
    return True
