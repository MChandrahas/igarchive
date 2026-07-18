"""progress.json — what's done, what's pending. The resume plan (D-008, KE-004).

Commit-then-record: a shortcode is marked only after its media is on disk AND its
metadata is captured. Writes are atomic (temp file + os.replace) so a crash mid-write
never corrupts the state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class Progress:
    def __init__(self, archive_dir: Path) -> None:
        self.path = archive_dir / "progress.json"
        self._completed_posts: set[str] = set()
        self._completed_highlights: set[str] = set()
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._completed_posts = set(data.get("completed_posts", []))
            self._completed_highlights = set(data.get("completed_highlights", []))

    @property
    def completed_posts(self) -> set[str]:
        return set(self._completed_posts)

    @property
    def completed_highlights(self) -> set[str]:
        return set(self._completed_highlights)

    def post_done(self, shortcode: str) -> bool:
        return shortcode in self._completed_posts

    def highlight_done(self, highlight_id: str) -> bool:
        return highlight_id in self._completed_highlights

    def mark_post(self, shortcode: str) -> None:
        self._completed_posts.add(shortcode)
        self._write()

    def mark_highlight(self, highlight_id: str) -> None:
        self._completed_highlights.add(highlight_id)
        self._write()

    def _write(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "completed_posts": sorted(self._completed_posts),
                    "completed_highlights": sorted(self._completed_highlights),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
