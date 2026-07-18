"""Backfill creator-chosen cover images for video media in an existing archive.

Usage:  .venv\\Scripts\\python.exe scripts\\backfill_covers.py <username>

Resumable: skips items that already have a thumbnail; writes atomically per post.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx
import instaloader

from igarchive.fetcher import Throttle, opt
from igarchive.media import download
from igarchive.schema import Archive
from igarchive.session import load_saved


def write_atomic(path: Path, archive: Archive) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def main() -> None:
    username = sys.argv[1]
    archives_root = Path("archives")
    archive_dir = archives_root / username
    profile_path = archive_dir / "profile.json"
    archive = Archive.model_validate_json(profile_path.read_text(encoding="utf-8"))

    loader = load_saved(archives_root)
    if loader is None:
        sys.exit("No valid session — import one in the app first.")

    throttle = Throttle()
    updated = 0
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for p in archive.posts:
            videos = [(i, m) for i, m in enumerate(p.media, start=1)
                      if m.kind == "video" and not m.thumbnail_local_path]
            if not videos:
                continue
            try:
                post = throttle.call(
                    lambda sc=p.shortcode: instaloader.Post.from_shortcode(loader.context, sc)
                )
            except instaloader.exceptions.InstaloaderException as e:
                print(f"{p.shortcode}: unavailable on Instagram ({type(e).__name__}) — skipped")
                continue
            covers: dict[int, str | None] = {}
            if post.typename == "GraphSidecar":
                nodes = throttle.call(lambda po=post: list(po.get_sidecar_nodes()))
                covers = {i: (n.display_url if n.is_video else None)
                          for i, n in enumerate(nodes, start=1)}
            else:
                covers = {1: opt(lambda po=post: po.url)}
            for i, m in videos:
                cover_url = covers.get(i)
                if not cover_url:
                    print(f"{p.shortcode}[{i}]: no cover in metadata")
                    continue
                rel = f"media/{p.shortcode}/{i:03d}_cover.jpg"
                try:
                    throttle.call(lambda u=cover_url, r=rel: download(
                        client, u, archive_dir / r, None))
                except Exception:  # noqa: BLE001 — cover is a nice-to-have
                    print(f"{p.shortcode}[{i}]: cover download failed")
                    continue
                m.thumbnail_local_path = rel
                updated += 1
                print(f"{p.shortcode}[{i}]: cover saved")
            write_atomic(profile_path, archive)

    print(f"\nDone: {updated} covers added ({throttle.requests_made} requests used).")


if __name__ == "__main__":
    main()
