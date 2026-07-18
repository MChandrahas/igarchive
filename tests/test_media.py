"""Quality regression — the download path must be byte-identical (D-004, KE-013)."""

from datetime import datetime, timezone
from pathlib import Path

import httpx

from igarchive.media import download

FIXTURE_BYTES = bytes(range(256)) * 512  # arbitrary binary payload; any re-encode would alter it


def test_download_is_byte_identical(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=FIXTURE_BYTES))
    dest = tmp_path / "media" / "SC123" / "001.jpg"
    taken = datetime(2026, 7, 8, 7, 14, tzinfo=timezone.utc)
    with httpx.Client(transport=transport) as client:
        download(client, "https://scontent.example/x.jpg", dest, taken)
    assert dest.read_bytes() == FIXTURE_BYTES
    assert abs(dest.stat().st_mtime - taken.timestamp()) < 2  # mtime restored to post date


def test_download_raises_on_http_error(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(429))
    with httpx.Client(transport=transport) as client:
        try:
            download(client, "https://x.example/x.jpg", tmp_path / "x.jpg", None)
        except httpx.HTTPStatusError as e:
            assert e.response.status_code == 429
        else:  # pragma: no cover
            raise AssertionError("expected HTTPStatusError")
