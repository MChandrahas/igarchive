"""The quarantine zone. ALL raw-metadata access lives here — nowhere else (D-006).

This is the module most likely to break when Instagram reshuffles its response
shape (KE-007). Every key access is defensive: a missing key yields None, never
a KeyError. A music failure must never abort a download.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Probe in order, take the first hit, log which matched (KE-008).
# Add new paths as Instagram shifts; never remove old ones.
CANDIDATE_PATHS: list[tuple[str, ...]] = [
    ("clips_metadata", "music_info", "music_asset_info"),  # reels
    ("music_metadata", "music_info", "music_asset_info"),  # photo + sticker (app shape)
    ("music_info", "music_asset_info"),  # photo + sticker (flat shape)
    ("clips_music_attribution_info",),  # reels (GraphQL shape)
    ("clips_metadata", "original_sound_info"),  # original audio (KE-011)
]

# Key aliases across the shapes above: (ours, candidates-in-order).
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "song_name"),
    "artist": ("display_artist", "artist_name"),
    "audio_id": ("audio_id", "audio_asset_id", "id"),
    "audio_url": ("progressive_download_url", "fast_start_progressive_download_url"),
}


@dataclass(frozen=True)
class ExtractedMusic:
    title: str | None
    artist: str | None
    audio_id: str | None
    # Remote URL when Instagram exposed one (photos: often absent — KE-009).
    audio_url: str | None
    # Creator-chosen segment (music_consumption_info); None when the shape lacks it.
    snippet_start_ms: int | None = None
    snippet_duration_ms: int | None = None


def _dig(raw: Any, path: tuple[str, ...]) -> Any:
    node = raw
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _snippet(raw: dict[str, Any], path: tuple[str, ...]) -> tuple[int | None, int | None]:
    """Snippet start/duration from music_consumption_info, a sibling of music_asset_info."""
    if path[-1] != "music_asset_info":
        return None, None
    parent = _dig(raw, path[:-1])
    ci = parent.get("music_consumption_info") if isinstance(parent, dict) else None
    if not isinstance(ci, dict):
        return None, None
    start = ci.get("audio_asset_start_time_in_ms")
    dur = ci.get("overlap_duration_in_ms")
    return (start if isinstance(start, int) else None, dur if isinstance(dur, int) else None)


def _first(block: dict[str, Any], field: str) -> str | None:
    for alias in _FIELD_ALIASES[field]:
        value = block.get(alias)
        if value is not None:
            return str(value)
    return None


def extract_music(raw: dict[str, Any]) -> ExtractedMusic | None:
    """Return music info from a post's raw metadata dict, or None if the post has none.

    The sole public surface of this module. Never raises.
    """
    for path in CANDIDATE_PATHS:
        block = _dig(raw, path)
        if isinstance(block, dict) and block:
            log.debug("music_path_matched", path="/".join(path))
            if "original_sound_info" in path:
                owner = block.get("ig_artist")
                username = owner.get("username") if isinstance(owner, dict) else None
                return ExtractedMusic(
                    title=f"Original audio · {username}" if username else "Original audio",
                    artist=None,
                    audio_id=_first(block, "audio_id"),
                    audio_url=_first(block, "audio_url"),
                )
            start, dur = _snippet(raw, path)
            return ExtractedMusic(
                title=_first(block, "title"),
                artist=_first(block, "artist"),
                audio_id=_first(block, "audio_id"),
                audio_url=_first(block, "audio_url"),
                snippet_start_ms=start,
                snippet_duration_ms=dur,
            )
    # No path matched. A non-empty music_info without music_asset_info under it means
    # the nesting changed — the early-warning signal for KE-008. Log loudly.
    # ponytail: heuristic only covers music_asset_info parents; widen if new shapes appear
    for path in CANDIDATE_PATHS:
        if path[-1] == "music_asset_info":
            parent = _dig(raw, path[:-1])
            if isinstance(parent, dict) and parent:
                log.warning("music_shape_shifted", probed="/".join(path))
    return None


def extract_from_post(post: Any) -> ExtractedMusic | None:
    """Fetch a Post's raw metadata and extract music. Part of the quarantine —
    callers wrap this in the network throttle (the first access may hit the API;
    Instaloader caches it afterwards).

    Probes the web graphql metadata first, then the mobile (v1) API struct — since
    PR-2706's converted graphql shape carries no music at all, the v1 struct is
    currently the only live source (KE-025 update).
    """
    music = extract_music(post._full_metadata)
    if music is not None:
        return music
    try:
        return extract_music(post._iphone_struct)
    except Exception:  # noqa: BLE001 — unofficial path; a miss is a gap, never a crash (KE-007)
        log.debug("iphone_struct_unavailable")
        return None


def dimensions_from_post(post: Any) -> tuple[int, int] | None:
    """(width, height) from the raw metadata, or None if the shape changed.

    Quarantined here with the rest of the raw-dict access (D-006) — Instaloader's
    public Post API doesn't expose dimensions.
    """
    dims = _dig(post._full_metadata, ("dimensions",))
    if isinstance(dims, dict):
        w, h = dims.get("width"), dims.get("height")
        if isinstance(w, int) and isinstance(h, int):
            return w, h
    try:  # v1 fallback — the PR-2706 graphql shape has no dimensions either
        s = post._iphone_struct
        w, h = s.get("original_width"), s.get("original_height")
        if isinstance(w, int) and isinstance(h, int):
            return w, h
    except Exception:  # noqa: BLE001 — same doctrine as above
        pass
    return None
