"""Double-click entry point: FastAPI on 127.0.0.1, auto-opens the browser (D-010).

Owns job orchestration and static serving. Contains no scraping logic.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

import instaloader
import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from .fetcher import FetchJob
from .session import SessionError, import_session, load_saved

HOST = "127.0.0.1"  # never 0.0.0.0 (KE-023)
PORT = 8123

PKG_DIR = Path(__file__).parent
VIEWER_DIR = PKG_DIR / "viewer"
UI_DIR = PKG_DIR / "ui"


def archives_root() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller: archives live next to the exe
        return Path(sys.executable).parent / "archives"
    return Path.cwd() / "archives"


app = FastAPI()
_loader: instaloader.Instaloader | None = None
_loader_checked = False
_job: FetchJob | None = None
_serve_only: Path | None = None


class ImportRequest(BaseModel):
    sessionid: str | None = None


class DownloadRequest(BaseModel):
    username: str
    comments: bool = False
    highlights: bool = True


@app.get("/")
def control() -> Response:
    if _serve_only is not None:
        # The viewer's asset paths are relative; it only works under /view/<name>/.
        return RedirectResponse(f"/view/{_serve_only.name}/")
    return FileResponse(UI_DIR / "control.html")


@app.get("/api/session")
def session_status() -> dict[str, Any]:
    global _loader, _loader_checked
    if _loader is None and not _loader_checked:
        _loader_checked = True
        _loader = load_saved(archives_root())
    username = _loader.context.username if _loader is not None else None
    return {"active": _loader is not None, "username": username}


@app.post("/api/session/import")
def session_import(req: ImportRequest) -> dict[str, Any]:
    global _loader
    try:
        _loader = import_session(archives_root(), req.sessionid)
    except SessionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"active": True, "username": _loader.context.username}


@app.post("/api/download")
def start_download(req: DownloadRequest) -> dict[str, str]:
    global _job
    if _loader is None:
        raise HTTPException(status_code=400, detail="Import a session first.")
    if _job is not None and _job.status["state"] in ("ENUMERATING", "FETCHING"):
        raise HTTPException(status_code=409, detail="A download is already running.")
    _job = FetchJob(
        _loader,
        req.username.strip().lstrip("@"),
        archives_root(),
        with_comments=req.comments,
        with_highlights=req.highlights,
    )
    threading.Thread(target=_job.run, daemon=True).start()
    return {"state": "started"}


@app.post("/api/cancel")
def cancel() -> dict[str, str]:
    if _job is not None:
        _job.cancel_requested = True
    return {"state": "cancelling"}


@app.post("/api/quit")
def quit_app() -> dict[str, str]:
    # A web server has no natural "off"; give the UI a real Quit. os._exit takes
    # down both the app and the PyInstaller bootloader parent, so nothing lingers.
    if _job is not None and _job.status["state"] in ("ENUMERATING", "FETCHING"):
        raise HTTPException(status_code=409, detail="A download is running — stop it first.")
    threading.Timer(0.3, lambda: os._exit(0)).start()  # after this response flushes
    return {"state": "quitting"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    root = archives_root()
    archives = sorted(p.parent.name for p in root.glob("*/profile.json")) if root.exists() else []
    job = dict(_job.status, username=_job.username) if _job is not None else None
    return {"job": job, "archives": archives}


NO_CACHE = {"Cache-Control": "no-cache"}  # revalidate every load; media may cache freely


def _archive_file(archive_dir: Path, path: str) -> FileResponse:
    target = (archive_dir / path).resolve()
    if not target.is_relative_to(archive_dir.resolve()) or not target.is_file():
        raise HTTPException(status_code=404)
    headers = NO_CACHE if target.name == "profile.json" else None
    return FileResponse(target, headers=headers)


@app.get("/view/{username}/{path:path}")
def view(username: str, path: str) -> FileResponse:
    archive_dir = _serve_only if _serve_only is not None else archives_root() / username
    if "/" in username or "\\" in username or not archive_dir.is_dir():
        raise HTTPException(status_code=404)
    if path in ("", "index.html", "app.js", "style.css"):
        return FileResponse(VIEWER_DIR / (path or "index.html"), headers=NO_CACHE)
    return _archive_file(archive_dir, path)


def main() -> None:
    global _serve_only
    parser = argparse.ArgumentParser(prog="igarchive")
    parser.add_argument("--dev", action="store_true", help="dev mode (no auto browser open)")
    parser.add_argument(
        "--serve-only",
        type=Path,
        default=None,
        metavar="ARCHIVE_DIR",
        help="serve an existing archive's viewer only; no network features",
    )
    args = parser.parse_args()
    _serve_only = args.serve_only.resolve() if args.serve_only else None

    url = (
        f"http://{HOST}:{PORT}/view/{_serve_only.name}/"
        if _serve_only
        else f"http://{HOST}:{PORT}/"
    )
    if not args.dev:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"igarchive running at {url}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
