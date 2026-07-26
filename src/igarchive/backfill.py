"""Re-probe music for posts captured while music extraction was broken (KE-025).

Music no longer rides along in Instagram's profile-enumeration response, so a
normal crawl leaves many posts with `music: null`. This pass re-fetches each
music-less post individually (`Post.from_shortcode`), which carries the mobile-API
metadata where the music block still lives, and patches `profile.json` in place.
Media is untouched.

The crawler chains this automatically after a completed run (launcher); it is also
runnable standalone via `scripts/backfill_music.py <username>`.

Resumable: writes profile.json atomically after every post; posts that already have
music WITH snippet timing are skipped, so re-running continues where it stopped.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import instaloader

from .fetcher import Throttle
from .media import download
from .music import extract_from_post
from .schema import Archive, Music
from .session import load_saved


def write_atomic(path: Path, archive: Archive) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(archive.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def backfill(
    username: str,
    archives_root: Path,
    loader: instaloader.Instaloader | None = None,
) -> int:
    """Add music (and audio files) to music-less posts in an archive. Returns the
    number of posts updated. Reuses the caller's session when one is passed.
    """
    archive_dir = archives_root / username
    profile_path = archive_dir / "profile.json"
    archive = Archive.model_validate_json(profile_path.read_text(encoding="utf-8"))

    if loader is None:
        loader = load_saved(archives_root)
    if loader is None:
        raise RuntimeError("No valid session — import one in the app first.")
    context = loader.context  # narrowed; Throttle.call runs each closure immediately

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
                    lambda: instaloader.Post.from_shortcode(context, p.shortcode)
                )
                extracted = throttle.call(lambda: extract_from_post(post))
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
                    audio_url = str(extracted.audio_url)
                    try:
                        throttle.call(
                            lambda: download(client, audio_url, archive_dir / rel, None)
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
    return updated
