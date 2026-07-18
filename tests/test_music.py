"""music.py — the quarantine zone. Fixture dicts only, never the live API."""

from typing import Any

from igarchive.music import extract_from_post, extract_music

REEL_SHAPE: dict[str, Any] = {
    "clips_metadata": {
        "music_info": {
            "music_asset_info": {
                "title": "Holocene",
                "display_artist": "Bon Iver",
                "audio_id": "aud_88213",
                "progressive_download_url": "https://cdn.example/holocene.m4a",
            }
        }
    }
}

PHOTO_STICKER_SHAPE: dict[str, Any] = {
    "music_info": {
        "music_asset_info": {
            "title": "Flightless Bird",
            "display_artist": "Iron & Wine",
            "audio_id": "aud_11111",
        },
        "music_consumption_info": {
            "audio_asset_start_time_in_ms": 164346,
            "overlap_duration_in_ms": 50000,
        },
    }
}

GRAPHQL_ATTRIBUTION_SHAPE: dict[str, Any] = {
    "clips_music_attribution_info": {
        "song_name": "Motion",
        "artist_name": "Ana Roxanne",
        "audio_id": "aud_22222",
    }
}

ORIGINAL_AUDIO_SHAPE: dict[str, Any] = {
    "clips_metadata": {
        "original_sound_info": {
            "ig_artist": {"username": "mara.fjord"},
            "audio_asset_id": "aud_33333",
        }
    }
}


def test_reel_shape() -> None:
    m = extract_music(REEL_SHAPE)
    assert m is not None
    assert (m.title, m.artist, m.audio_id) == ("Holocene", "Bon Iver", "aud_88213")
    assert m.audio_url == "https://cdn.example/holocene.m4a"


def test_photo_sticker_shape_without_url() -> None:
    # KE-009: metadata present, no audio URL — that's normal, not an error.
    m = extract_music(PHOTO_STICKER_SHAPE)
    assert m is not None and m.title == "Flightless Bird" and m.audio_url is None


def test_snippet_timing_extracted() -> None:
    # Instagram plays the creator-chosen segment; capture its offsets when present.
    m = extract_music(PHOTO_STICKER_SHAPE)
    assert m is not None
    assert (m.snippet_start_ms, m.snippet_duration_ms) == (164346, 50000)


def test_snippet_absent_is_none() -> None:
    m = extract_music(REEL_SHAPE)  # no music_consumption_info in this fixture
    assert m is not None and m.snippet_start_ms is None and m.snippet_duration_ms is None


def test_graphql_attribution_shape_key_aliases() -> None:
    m = extract_music(GRAPHQL_ATTRIBUTION_SHAPE)
    assert m is not None and (m.title, m.artist) == ("Motion", "Ana Roxanne")


def test_original_audio(caplog: object) -> None:
    # KE-011: no track metadata — label it, don't leave an empty song bar.
    m = extract_music(ORIGINAL_AUDIO_SHAPE)
    assert m is not None and m.title == "Original audio · mara.fjord" and m.artist is None


def test_no_music_returns_none() -> None:
    assert extract_music({}) is None
    assert extract_music({"caption": "hi"}) is None


def test_no_music_reel_returns_none() -> None:
    # clips_metadata exists on every reel; its presence alone is not music.
    assert extract_music({"clips_metadata": {"music_info": None, "audio_type": None}}) is None


class _FakePost:
    """Mimics the two raw structs a Post exposes — no network, no instaloader."""

    def __init__(self, full: dict[str, Any], iphone: dict[str, Any] | None) -> None:
        self._full_metadata = full
        self._iphone = iphone

    @property
    def _iphone_struct(self) -> dict[str, Any]:
        if self._iphone is None:
            raise RuntimeError("iphone api unavailable")
        return self._iphone


def test_falls_back_to_iphone_struct_when_graphql_is_bare() -> None:
    # KE-025: the PR-2706 graphql shape has no music; the v1 struct still does.
    post = _FakePost(full={"shortcode": "x", "is_video": True}, iphone=REEL_SHAPE)
    m = extract_from_post(post)
    assert m is not None and m.title == "Holocene"


def test_iphone_struct_failure_is_a_gap_not_a_crash() -> None:
    post = _FakePost(full={"shortcode": "x"}, iphone=None)
    assert extract_from_post(post) is None


def test_shape_shift_never_raises() -> None:
    # KE-007: a reshuffled response yields None, never a KeyError.
    shifted = {"music_info": {"renamed_asset_block": {"title": "X"}}}
    assert extract_music(shifted) is None
    assert extract_music({"clips_metadata": "unexpected-string"}) is None
    assert extract_music({"music_info": {"music_asset_info": None}}) is None
