"""Backfill music metadata (and audio files) for archives captured while music
extraction was broken (KE-025). Media is untouched; only profile.json gains music.

Usage:  .venv\\Scripts\\python.exe scripts\\backfill_music.py <username>

Resumable: writes profile.json atomically after every post; posts that already
have music are skipped, so re-running continues where it stopped.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx
import instaloader

from igarchive.fetcher import Throttle
from igarchive.media import download
from igarchive.music import extract_from_post
from igarchive.schema import Archive, Music
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
            # Skip only when we already have music WITH snippet timing; re-probe
            # music-bearing posts captured before snippet support existed.
            if p.music is not None and p.music.snippet_start_ms is not None:
                continue
            try:
                post = throttle.call(
                    lambda sc=p.shortcode: instaloader.Post.from_shortcode(loader.context, sc)
                )
                extracted = throttle.call(lambda po=post: extract_from_post(po))
            except instaloader.exceptions.InstaloaderException as e:
                # Deleted/unavailable post — it lives only in the archive now; no
                # metadata to fetch. A gap, not a crash.
                print(f"{p.shortcode}: unavailable on Instagram ({type(e).__name__}) — skipped")
                continue
            if extracted is None:
                print(f"{p.shortcode}: no music")
                continue
            # Reels: reuse the m4a already stream-copied from the mp4. Otherwise, take
            # the direct asset URL when Instagram exposed one (KE-009).
            audio_rel = next((m.audio_local_path for m in p.media if m.audio_local_path), None)
            if audio_rel is None and extracted.audio_url:
                rel = f"media/{p.shortcode}/music.m4a"
                if (archive_dir / rel).exists():  # downloaded on a previous pass
                    audio_rel = rel
                else:
                    try:
                        throttle.call(
                            lambda u=extracted.audio_url, r=rel: download(
                                client, str(u), archive_dir / r, None
                            )
                        )
                        audio_rel = rel
                    except Exception:  # noqa: BLE001 — a missing audio file is a gap, not a failure
                        pass
            p.music = Music(
                title=extracted.title,
                artist=extracted.artist,
                audio_id=extracted.audio_id,
                audio_local_path=audio_rel,
                snippet_start_ms=extracted.snippet_start_ms,
                snippet_duration_ms=extracted.snippet_duration_ms,
            )
            updated += 1
            print(f"{p.shortcode}: {extracted.title or '?'} — {extracted.artist or ''}"
                  f"{' [audio saved]' if audio_rel else ' [no audio file]'}")
            archive.capture_stats.audio_files_missing = sum(
                1 for x in archive.posts if x.music and not x.music.audio_local_path
            )
            write_atomic(profile_path, archive)

    print(f"\nDone: music added to {updated} posts "
          f"({throttle.requests_made} requests used).")


if __name__ == "__main__":
    main()
