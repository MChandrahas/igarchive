"""Pydantic models for profile.json — the single source of truth for the contract.

No business logic here. Fetcher constructs these, viewer reads the JSON they emit.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, field_validator

SCHEMA_VERSION = 1


def _require_relative(path: str | None) -> str | None:
    # KE-018: absolute paths make archives unmovable.
    if path is not None and (PurePosixPath(path).is_absolute() or ":" in path.split("/")[0]):
        raise ValueError(f"local_path must be relative to the archive root: {path!r}")
    return path


class FileRef(BaseModel):
    local_path: str | None = None
    remote_url: str | None = None

    _rel = field_validator("local_path")(_require_relative)


class CaptureOptions(BaseModel):
    authenticated: bool
    comments: bool
    highlights: bool


class CaptureStats(BaseModel):
    posts_captured: int = 0
    highlights_captured: int = 0
    comments_captured: int = 0
    audio_files_missing: int = 0
    incomplete: bool = True


class Profile(BaseModel):
    username: str
    full_name: str
    biography: str
    external_url: str | None = None
    followers: int
    following: int
    posts_count: int
    is_verified: bool
    is_private: bool
    avatar: FileRef


class Music(BaseModel):
    title: str | None = None
    artist: str | None = None
    audio_id: str | None = None
    # None = there was music but no file obtainable (distinct from Post.music = None).
    audio_local_path: str | None = None
    # Creator-chosen segment of the track (Instagram plays this part, not the whole
    # song). None = unknown → viewer falls back to full-track playback.
    snippet_start_ms: int | None = None
    snippet_duration_ms: int | None = None

    _rel = field_validator("audio_local_path")(_require_relative)


class MediaItem(BaseModel):
    kind: Literal["image", "video"]
    local_path: str
    remote_url: str | None = None
    width: int
    height: int
    duration: float | None = None
    audio_local_path: str | None = None
    # Videos: the creator-chosen cover image (reel covers differ from frame 1).
    thumbnail_local_path: str | None = None

    _rel = field_validator("local_path", "audio_local_path", "thumbnail_local_path")(
        _require_relative
    )


class Comment(BaseModel):
    username: str
    text: str
    created_at: datetime
    likes: int = 0
    replies: list[Comment] = []


class Post(BaseModel):
    shortcode: str
    type: Literal["image", "carousel", "reel"]
    taken_at: datetime
    caption: str | None = None
    likes: int = 0
    views: int | None = None
    location: str | None = None
    source_url: str
    media: list[MediaItem]  # always a list — a single photo is a carousel of length 1
    music: Music | None = None
    comments_captured: bool = False
    comments: list[Comment] = []


class HighlightItem(BaseModel):
    kind: Literal["image", "video"]
    local_path: str
    taken_at: datetime | None = None
    width: int
    height: int
    duration: float | None = None
    audio_local_path: str | None = None

    _rel = field_validator("local_path", "audio_local_path")(_require_relative)


class Highlight(BaseModel):
    id: str
    title: str
    cover: FileRef
    items: list[HighlightItem] = []


class Archive(BaseModel):
    schema_version: int = SCHEMA_VERSION
    captured_at: datetime
    source_url: str
    capture_options: CaptureOptions
    capture_stats: CaptureStats
    profile: Profile
    highlights: list[Highlight] = []
    posts: list[Post] = []
