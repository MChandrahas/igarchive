"""Builds and emits profile.json against schema.py. Makes no network calls.

The file is rewritten after every committed post so an interrupted run still
leaves a valid, loadable archive (KE-004). Writes are atomic.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .schema import Archive, CaptureOptions, CaptureStats, Highlight, Post, Profile


class ArchiveWriter:
    def __init__(
        self,
        archive_dir: Path,
        source_url: str,
        options: CaptureOptions,
        profile: Profile,
        keep_posts: set[str],
        keep_highlights: set[str],
    ) -> None:
        self.path = archive_dir / "profile.json"
        posts: list[Post] = []
        highlights: list[Highlight] = []
        if self.path.exists():
            # Resume: keep only entries progress.json confirms were fully committed.
            previous = Archive.model_validate_json(self.path.read_text(encoding="utf-8"))
            posts = [p for p in previous.posts if p.shortcode in keep_posts]
            highlights = [h for h in previous.highlights if h.id in keep_highlights]
        self.archive = Archive(
            captured_at=datetime.now(timezone.utc),
            source_url=source_url,
            capture_options=options,
            capture_stats=CaptureStats(incomplete=True),
            profile=profile,
            highlights=highlights,
            posts=posts,
        )
        self.write()

    def upsert_post(self, post: Post) -> None:
        self.archive.posts = [p for p in self.archive.posts if p.shortcode != post.shortcode]
        self.archive.posts.append(post)
        self.write()

    def upsert_highlight(self, highlight: Highlight) -> None:
        self.archive.highlights = [h for h in self.archive.highlights if h.id != highlight.id]
        self.archive.highlights.append(highlight)
        self.write()

    def add_missing_audio(self) -> None:
        self.archive.capture_stats.audio_files_missing += 1

    def finalize(self) -> None:
        self.archive.capture_stats.incomplete = False
        self.write()

    def write(self) -> None:
        stats = self.archive.capture_stats
        stats.posts_captured = len(self.archive.posts)
        stats.highlights_captured = len(self.archive.highlights)
        stats.comments_captured = sum(len(p.comments) for p in self.archive.posts)
        self.archive.posts.sort(key=lambda p: p.taken_at, reverse=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(self.archive.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
