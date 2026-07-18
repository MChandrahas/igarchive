"""Session import — an existing browser cookie jar, nothing else (D-009).

This module never accepts, prompts for, or stores a password. A dead session is
reported plainly with a re-import instruction, never a credential fallback.
Cookie values are never logged.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import instaloader
import structlog

log = structlog.get_logger(__name__)

SESSION_FILE = ".session.json"

# Cookies minted in a browser get used with that browser's UA — a Chrome default UA
# with Firefox-minted cookies is a fingerprint mismatch that trips 403s on graphql.
FIREFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"


class SessionError(Exception):
    """User-facing session problem. The message names the fix."""


def _firefox_profile_dirs() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        roots = [home / "AppData/Roaming/Mozilla/Firefox/Profiles"]
    elif sys.platform == "darwin":
        roots = [home / "Library/Application Support/Firefox/Profiles"]
    else:
        roots = [home / ".mozilla/firefox", home / "snap/firefox/common/.mozilla/firefox"]
    return [p for root in roots if root.exists() for p in root.iterdir() if p.is_dir()]


def _firefox_cookies() -> dict[str, str]:
    # ponytail: Firefox only — Chrome cookies are OS-keychain/app-bound encrypted (KE-024);
    # Chrome users paste their sessionid cookie instead. Add decryption only if demanded.
    candidates = sorted(
        (p / "cookies.sqlite" for p in _firefox_profile_dirs() if (p / "cookies.sqlite").exists()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        tried = ", ".join(str(p) for p in _firefox_profile_dirs()) or "no Firefox profile found"
        raise SessionError(
            "Couldn't find Firefox cookies. Log into Instagram in Firefox first, "
            f"or paste your sessionid cookie instead. Paths tried: {tried}"
        )
    # Copy first — the DB is locked while Firefox runs.
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        shutil.copyfile(candidates[0], tmp.name)
        con = sqlite3.connect(tmp.name)
        try:
            rows = con.execute(
                "SELECT name, value FROM moz_cookies WHERE host LIKE '%instagram.com'"
            ).fetchall()
        finally:
            con.close()
    cookies = {name: value for name, value in rows}
    if "sessionid" not in cookies:
        raise SessionError(
            "Firefox has Instagram cookies but no active login. "
            "Log into Instagram in Firefox (use a burner account), then re-import."
        )
    return cookies


def _validate(loader: instaloader.Instaloader) -> str:
    username = loader.test_login()
    if not username:
        raise SessionError(
            "That session isn't logged in. Log into Instagram in your browser "
            "(use a burner account, never your main), then re-import."
        )
    loader.context.username = username  # type: ignore[assignment]
    return username


def _new_loader() -> instaloader.Instaloader:
    return instaloader.Instaloader(
        quiet=True,
        user_agent=FIREFOX_UA,
        download_pictures=False,  # we stream media ourselves (D-004)
        download_videos=False,
        download_video_thumbnails=False,
        save_metadata=False,
        compress_json=False,
        max_connection_attempts=1,
    )


def _loader_from_cookies(cookies: dict[str, str]) -> instaloader.Instaloader:
    loader = _new_loader()
    loader.context._session.cookies.update(cookies)  # documented import-from-browser recipe
    return loader


def parse_pasted_cookies(pasted: str) -> dict[str, str]:
    """Accept a bare sessionid value or a full 'name=v; name2=v2' cookie string.

    A lone sessionid sometimes works, but graphql endpoints 403 without the full
    jar (csrftoken, ds_user_id, mid) — pasting all of document.cookie is safer.
    """
    if "=" not in pasted:
        return {"sessionid": pasted.strip()}
    cookies: dict[str, str] = {}
    for part in pasted.split(";"):
        name, _, value = part.strip().partition("=")
        if name and value:
            cookies[name] = value.strip('"')
    if "sessionid" not in cookies:
        raise SessionError(
            "No sessionid in the pasted cookies. Copy the sessionid cookie value — or the "
            "whole cookie string — from a browser that's logged into Instagram."
        )
    return cookies


def import_session(archives_dir: Path, sessionid: str | None = None) -> instaloader.Instaloader:
    """Build a logged-in loader from a pasted cookie (jar) or the Firefox jar."""
    cookies = parse_pasted_cookies(sessionid) if sessionid else _firefox_cookies()
    loader = _loader_from_cookies(cookies)
    username = _validate(loader)
    archives_dir.mkdir(parents=True, exist_ok=True)
    (archives_dir / SESSION_FILE).write_text(json.dumps(cookies), encoding="utf-8")
    log.info("session_imported", username=username)  # never log cookie values
    return loader


def load_saved(archives_dir: Path) -> instaloader.Instaloader | None:
    """Reload a previously imported session, or None if there isn't a valid one."""
    path = archives_dir / SESSION_FILE
    if not path.exists():
        return None
    try:
        loader = _loader_from_cookies(json.loads(path.read_text(encoding="utf-8")))
        _validate(loader)
    except (SessionError, instaloader.exceptions.InstaloaderException, ValueError):
        log.info("saved_session_invalid")  # stale file means "re-import", not a crash
        return None
    return loader
