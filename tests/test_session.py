"""Cookie parsing — no network, no real cookies (KE-025)."""

import pytest

from igarchive.session import SessionError, parse_pasted_cookies


def test_bare_sessionid() -> None:
    assert parse_pasted_cookies(" abc123%3Axyz ") == {"sessionid": "abc123%3Axyz"}


def test_full_cookie_string() -> None:
    pasted = 'csrftoken=tok; ds_user_id=42; sessionid="42%3Aabc"; mid=m-1'
    cookies = parse_pasted_cookies(pasted)
    assert cookies == {
        "csrftoken": "tok",
        "ds_user_id": "42",
        "sessionid": "42%3Aabc",
        "mid": "m-1",
    }


def test_cookie_string_without_sessionid_rejected() -> None:
    with pytest.raises(SessionError):
        parse_pasted_cookies("csrftoken=tok; mid=m-1")
