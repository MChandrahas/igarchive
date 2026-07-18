"""Optional-field guard — missing metadata fields are gaps, never crashes (KE-026)."""

from igarchive.fetcher import opt


def test_opt_returns_value() -> None:
    assert opt(lambda: 21.7) == 21.7


def test_opt_swallows_missing_field() -> None:
    def missing() -> int:
        raise KeyError("video_duration")

    assert opt(missing) is None


def test_opt_swallows_type_error_from_none_dict() -> None:
    def broken() -> int:
        raise TypeError("'NoneType' object is not subscriptable")

    assert opt(broken) is None
