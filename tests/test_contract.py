"""Contract tests — the gate between the fetcher and the viewer (D-003).

The golden file covers every state combination in guidelines §2. If profile.json
changes shape, this suite fails first, on purpose.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from igarchive.schema import SCHEMA_VERSION, Archive, MediaItem, Music, Post

GOLDEN = Path(__file__).parent / "fixtures" / "profile.golden.json"

pytestmark = pytest.mark.contract


@pytest.fixture
def archive() -> Archive:
    return Archive.model_validate_json(GOLDEN.read_text(encoding="utf-8"))


def test_golden_round_trip(archive: Archive) -> None:
    assert archive.schema_version == SCHEMA_VERSION
    again = Archive.model_validate_json(archive.model_dump_json())
    assert again == archive


def test_media_is_always_a_list(archive: Archive) -> None:
    # KE-019: a single image is a carousel of length 1 — never a bare object.
    for post in archive.posts:
        assert isinstance(post.media, list) and len(post.media) >= 1


def test_music_states_are_distinct(archive: Archive) -> None:
    # KE-010: music null vs music.audio_local_path null are different states.
    by_sc = {p.shortcode: p for p in archive.posts}
    with_audio = by_sc["REEL1234567"].music
    without_file = by_sc["PHOTOMUSIC1"].music
    no_music = by_sc["CAROUSEL111"].music
    assert with_audio is not None and with_audio.audio_local_path is not None
    assert without_file is not None and without_file.audio_local_path is None
    assert no_music is None


def test_comment_states_are_distinct(archive: Archive) -> None:
    # KE-017: empty + not captured ≠ empty + captured.
    by_sc = {p.shortcode: p for p in archive.posts}
    assert by_sc["CAROUSEL111"].comments == [] and not by_sc["CAROUSEL111"].comments_captured
    assert by_sc["SINGLEIMG01"].comments == [] and by_sc["SINGLEIMG01"].comments_captured
    assert by_sc["REEL1234567"].comments_captured and by_sc["REEL1234567"].comments


def test_all_local_paths_are_relative(archive: Archive) -> None:
    # KE-018: absolute paths make archives unmovable.
    paths: list[str] = [archive.profile.avatar.local_path or ""]
    for post in archive.posts:
        paths += [m.local_path for m in post.media]
        paths += [m.thumbnail_local_path for m in post.media if m.thumbnail_local_path]
        if post.music and post.music.audio_local_path:
            paths.append(post.music.audio_local_path)
    for hl in archive.highlights:
        paths += [hl.cover.local_path or ""] + [i.local_path for i in hl.items]
    for p in paths:
        assert not p.startswith("/") and ":" not in p.split("/")[0], p


def test_absolute_local_path_rejected() -> None:
    for bad in ["/abs/media/x.jpg", "C:/media/x.jpg", "C:\\media\\x.jpg"]:
        with pytest.raises(ValidationError):
            MediaItem(kind="image", local_path=bad, width=1, height=1)


def test_captions_preserved_verbatim(archive: Archive) -> None:
    # KE-020: emoji, RTL, newlines survive the round trip.
    assert "\n" in (next(p for p in archive.posts if p.shortcode == "REEL1234567").caption or "")
    assert "טקסט" in (next(p for p in archive.posts if p.shortcode == "SINGLEIMG01").caption or "")


def test_music_model_allows_metadata_without_file() -> None:
    m = Music(title="X", artist="Y", audio_id="z", audio_local_path=None)
    assert m.audio_local_path is None


def test_post_type_is_constrained() -> None:
    with pytest.raises(ValidationError):
        Post(
            shortcode="x",
            type="story",
            taken_at="2026-01-01T00:00:00Z",  # type: ignore[arg-type]
            source_url="https://instagram.com/p/x",
            media=[MediaItem(kind="image", local_path="media/x/001.jpg", width=1, height=1)],
        )
