"""Instaloader library calls, pagination, rate limiting, backoff (D-002, D-008).

Every outbound request goes through Throttle.call() — no other module makes a
bare network call. Jittered sleeps (never a metronome — KE-003), exponential
backoff on 429, a hard per-session ceiling, 401 is fatal (KE-001).
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Literal, TypeVar

import httpx
import instaloader
import structlog
from instaloader.exceptions import (
    ConnectionException,
    LoginRequiredException,
    TooManyRequestsException,
)

from . import media
from .music import ExtractedMusic, dimensions_from_post, extract_from_post
from .normalizer import ArchiveWriter
from .progress import Progress
from .schema import (
    CaptureOptions,
    Comment,
    FileRef,
    Highlight,
    HighlightItem,
    MediaItem,
    Music,
    Post,
    Profile,
)

T = TypeVar("T")
log = structlog.get_logger(__name__)

SLEEP_RANGE = (1.5, 4.5)  # jittered pause before every request
MAX_RETRIES = 5
REQUEST_CEILING = 800  # stop voluntarily before Instagram stops you


class FatalFetchError(Exception):
    """Halts the run cleanly. The message is user-facing and names the fix."""


class SessionExpired(FatalFetchError):
    def __init__(self) -> None:
        super().__init__("Your session expired — re-import it from your browser.")


class RequestCeilingReached(FatalFetchError):
    def __init__(self) -> None:
        super().__init__(
            "Session request ceiling reached — stopped on purpose to protect the account. "
            "Run again later; it resumes where it left off."
        )


def opt(fn: Callable[[], T]) -> T | None:
    """An Instaloader field that may be absent from the metadata shape.

    Instagram's response conversions (e.g. the PR-2706 format) drop fields that used
    to be guaranteed; Instaloader raises KeyError for them. A missing optional field
    is a gap to record, never a crash (KE-026).
    """
    try:
        return fn()
    except (KeyError, TypeError):
        return None


class Throttle:
    def __init__(self, on_pause: Callable[[str], None] | None = None) -> None:
        self.requests_made = 0
        self._on_pause = on_pause or (lambda msg: None)

    def call(self, fn: Callable[[], T]) -> T:
        if self.requests_made >= REQUEST_CEILING:
            raise RequestCeilingReached()
        self.requests_made += 1
        time.sleep(random.uniform(*SLEEP_RANGE))
        for attempt in range(MAX_RETRIES):
            try:
                return fn()
            except TooManyRequestsException:
                self._backoff(attempt)
            except LoginRequiredException as e:
                raise SessionExpired() from e  # fatal, never retried (KE-001)
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code == 401:
                    raise SessionExpired() from e
                if code == 429 or code >= 500:
                    self._backoff(attempt)
                else:
                    raise
        raise FatalFetchError(
            "Instagram kept rate-limiting after several backoffs — try again later; "
            "the run resumes where it left off."
        )

    def _backoff(self, attempt: int) -> None:
        pause = (2**attempt) * 30 * random.uniform(1.0, 1.5)
        log.warning("rate_limited", attempt=attempt, pause_s=round(pause))
        self._on_pause(f"Rate limited — pausing {round(pause)}s")
        time.sleep(pause)
        self._on_pause("")

    def iter(self, iterable: Iterable[T]) -> Iterator[T]:
        """Drive an Instaloader iterator with the wrapper around each pagination step."""
        it = iter(iterable)
        while True:
            try:
                yield self.call(lambda: next(it))
            except StopIteration:
                return


class FetchJob:
    """State machine: IDLE → ENUMERATING → FETCHING → COMPLETE | FAILED | INTERRUPTED."""

    def __init__(
        self,
        loader: instaloader.Instaloader,
        username: str,
        archives_root: Path,
        with_comments: bool = False,
        with_highlights: bool = True,
    ) -> None:
        self.loader = loader
        self.username = username
        self.archive_dir = archives_root / username
        self.media_dir = self.archive_dir / "media"
        self.with_comments = with_comments
        self.with_highlights = with_highlights
        self.status: dict[str, Any] = {"state": "IDLE", "done": 0, "total": 0, "message": ""}
        self.cancel_requested = False
        self.throttle = Throttle(on_pause=lambda m: self.status.__setitem__("message", m))

    def run(self) -> None:
        try:
            self._run()
        except FatalFetchError as e:
            interrupted = isinstance(e, RequestCeilingReached)
            self.status["state"] = "INTERRUPTED" if interrupted else "FAILED"
            self.status["message"] = str(e)
            log.warning("run_halted", reason=str(e))
        except ConnectionException as e:
            self.status["state"] = "INTERRUPTED"
            if "403" in str(e):
                # Bot-wall, not a dead session (that's a 401). See KE-025.
                self.status["message"] = (
                    "Instagram blocked the request (403 on graphql). Usual fixes, in order: "
                    "re-import the session with the FULL cookie jar (use 'Import from Firefox', "
                    "or paste the whole cookie string — not just sessionid); wait a few hours "
                    "(IP/account cool-down); and check for an Instaloader update — Instagram "
                    "periodically breaks the library for everyone until it ships a fix (KE-025). "
                    "The run resumes where it left off."
                )
            else:
                self.status["message"] = f"Connection problem — run again to resume. ({e})"
            log.warning("run_halted", reason=str(e))
        except Exception as e:
            # The job thread must never die silently — a stuck FETCHING bar is a lie (KE-026).
            self.status["state"] = "FAILED"
            self.status["message"] = (
                f"Unexpected error ({type(e).__name__}: {e}) — completed posts are safe; "
                "run again to resume from where it stopped."
            )
            log.error("run_crashed", exc_info=True)

    def _run(self) -> None:
        self.status["state"] = "ENUMERATING"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        progress = Progress(self.archive_dir)
        profile = self.throttle.call(
            lambda: instaloader.Profile.from_username(self.loader.context, self.username)
        )
        if profile.is_private and not profile.followed_by_viewer:
            raise FatalFetchError(
                f"@{self.username} is private and this session doesn't follow it. "
                "Private profiles are out of scope."
            )

        with httpx.Client(timeout=60, follow_redirects=True) as client:
            avatar = FileRef(local_path="media/avatar.jpg", remote_url=profile.profile_pic_url)
            self.throttle.call(
                lambda: media.download(
                    client, profile.profile_pic_url, self.media_dir / "avatar.jpg", None
                )
            )
            writer = ArchiveWriter(
                archive_dir=self.archive_dir,
                source_url=f"https://instagram.com/{profile.username}",
                options=CaptureOptions(
                    authenticated=True,
                    comments=self.with_comments,
                    highlights=self.with_highlights,
                ),
                profile=Profile(
                    username=profile.username,
                    full_name=profile.full_name,
                    biography=profile.biography,
                    external_url=profile.external_url,
                    followers=profile.followers,
                    following=profile.followees,
                    posts_count=profile.mediacount,
                    is_verified=profile.is_verified,
                    is_private=profile.is_private,
                    avatar=avatar,
                ),
                keep_posts=progress.completed_posts,
                keep_highlights=progress.completed_highlights,
            )
            self.status["state"] = "FETCHING"
            self.status["total"] = profile.mediacount

            for post in self.throttle.iter(profile.get_posts()):
                if self.cancel_requested:
                    self.status["state"] = "INTERRUPTED"
                    self.status["message"] = "Stopped — run again to resume."
                    return
                if progress.post_done(post.shortcode):
                    self.status["done"] += 1
                    continue
                writer.upsert_post(self._capture_post(client, post, writer))
                progress.mark_post(post.shortcode)  # commit-then-record (KE-004)
                self.status["done"] += 1

            if self.with_highlights:
                self.status["message"] = "Checking highlights…"
                for hl in self.throttle.iter(self.loader.get_highlights(profile)):
                    if progress.highlight_done(str(hl.unique_id)):
                        continue
                    # The post bar sits at 100% here — say what's happening (KE-026 adjacent).
                    self.status["message"] = f"Downloading highlight “{hl.title}”…"
                    writer.upsert_highlight(self._capture_highlight(client, hl))
                    progress.mark_highlight(str(hl.unique_id))

        writer.finalize()
        self.status["state"] = "COMPLETE"
        self.status["message"] = "Done"

    # -- per-entity capture -------------------------------------------------

    def _capture_post(
        self, client: httpx.Client, post: instaloader.Post, writer: ArchiveWriter
    ) -> Post:
        sc = post.shortcode
        taken = post.date_utc.replace(tzinfo=timezone.utc)
        items = self._capture_media(client, post, taken)
        post_type: Literal["image", "carousel", "reel"] = "image"
        if len(items) > 1:
            post_type = "carousel"
        elif items and items[0].kind == "video":
            post_type = "reel"
        return Post(
            shortcode=sc,
            type=post_type,
            taken_at=taken,
            caption=opt(lambda: post.caption),
            likes=opt(lambda: post.likes) or 0,
            views=opt(lambda: post.video_view_count) if post.is_video else None,
            location=None,  # ponytail: post.location costs an extra request per post; add if wanted
            source_url=f"https://instagram.com/p/{sc}",
            media=items,
            music=self._capture_music(client, post, items, writer),
            comments_captured=self.with_comments,
            comments=self._capture_comments(post) if self.with_comments else [],
        )

    def _capture_media(
        self, client: httpx.Client, post: instaloader.Post, taken: datetime
    ) -> list[MediaItem]:
        sc = post.shortcode
        # First raw-metadata touch for this post triggers one throttled request;
        # Instaloader caches it, so the later music extraction is free.
        dims = self.throttle.call(partial(dimensions_from_post, post)) or (1080, 1350)
        width, height = dims  # sidecar nodes don't expose dims; post's is close enough
        entries: list[tuple[bool, str | None, str | None]] = []  # (is_video, url, cover_url)
        if post.typename == "GraphSidecar":
            nodes = self.throttle.call(lambda: list(post.get_sidecar_nodes()))
            entries = [
                (n.is_video, n.video_url if n.is_video else n.display_url,
                 n.display_url if n.is_video else None)
                for n in nodes
            ]
        elif post.is_video:
            # post.url on a video is the creator-chosen cover image, not frame 1.
            entries = [(True, self.throttle.call(lambda: post.video_url), opt(lambda: post.url))]
        else:
            entries = [(False, post.url, None)]

        items: list[MediaItem] = []
        for i, (is_video, url, cover_url) in enumerate(entries, start=1):
            if not url:
                # Zero *silent* skips: the gap is logged and visible in the archive.
                log.error("media_url_missing", shortcode=sc, index=i)
                continue
            ext = "mp4" if is_video else "jpg"
            rel = f"media/{sc}/{i:03d}.{ext}"
            dest = self.archive_dir / rel
            self.throttle.call(partial(media.download, client, url, dest, taken))
            thumb_rel: str | None = None
            if cover_url:
                thumb_rel = f"media/{sc}/{i:03d}_cover.jpg"
                try:
                    self.throttle.call(
                        partial(media.download, client, cover_url, self.archive_dir / thumb_rel, taken)
                    )
                except FatalFetchError:
                    raise
                except Exception:  # a cover is a nice-to-have; the video itself is the record
                    log.warning("cover_download_failed", shortcode=sc, index=i)
                    thumb_rel = None
            log.info(
                "resolution_selected", shortcode=sc, width=width, height=height
            )  # KE-012 audit
            audio_rel: str | None = None
            if is_video:
                m4a = dest.with_suffix(".m4a")
                if media.extract_audio(dest, m4a):
                    audio_rel = f"media/{sc}/{i:03d}.m4a"
            items.append(
                MediaItem(
                    kind="video" if is_video else "image",
                    local_path=rel,
                    remote_url=url,
                    width=width,
                    height=height,
                    duration=opt(lambda: post.video_duration) if is_video else None,
                    audio_local_path=audio_rel,
                    thumbnail_local_path=thumb_rel,
                )
            )
        return items

    def _capture_music(
        self,
        client: httpx.Client,
        post: instaloader.Post,
        items: list[MediaItem],
        writer: ArchiveWriter,
    ) -> Music | None:
        # A music failure must never abort a download (KE-007).
        try:
            extracted: ExtractedMusic | None = self.throttle.call(lambda: extract_from_post(post))
        except FatalFetchError:
            raise
        except Exception:
            log.warning("music_extraction_failed", shortcode=post.shortcode, exc_info=True)
            return None
        if extracted is None:
            return None

        # Reels: the audio is already stream-copied out of the mp4.
        audio_rel = next((i.audio_local_path for i in items if i.audio_local_path), None)
        if audio_rel is None and extracted.audio_url:
            # Photos: opportunistic — sometimes there's a URL, sometimes not (KE-009).
            rel = f"media/{post.shortcode}/music.m4a"
            try:
                self.throttle.call(
                    lambda: media.download(
                        client, str(extracted.audio_url), self.archive_dir / rel, None
                    )
                )
                audio_rel = rel
            except FatalFetchError:
                raise
            except Exception:
                log.info("music_audio_unavailable", shortcode=post.shortcode)
        if audio_rel is None:
            writer.add_missing_audio()  # counted once at the end, not warned per-post (KE-009)
        return Music(
            title=extracted.title,
            artist=extracted.artist,
            audio_id=extracted.audio_id,
            audio_local_path=audio_rel,
            snippet_start_ms=extracted.snippet_start_ms,
            snippet_duration_ms=extracted.snippet_duration_ms,
        )

    def _capture_comments(self, post: instaloader.Post) -> list[Comment]:
        comments: list[Comment] = []
        for c in self.throttle.iter(post.get_comments()):
            comments.append(
                Comment(
                    username=c.owner.username,
                    text=c.text,
                    created_at=c.created_at_utc.replace(tzinfo=timezone.utc),
                    likes=c.likes_count,
                    replies=[
                        Comment(
                            username=a.owner.username,
                            text=a.text,
                            created_at=a.created_at_utc.replace(tzinfo=timezone.utc),
                            likes=a.likes_count,
                        )
                        for a in c.answers
                    ],
                )
            )
        return comments

    def _capture_highlight(self, client: httpx.Client, hl: instaloader.Highlight) -> Highlight:
        hid = str(hl.unique_id)
        cover_rel = f"media/hl/{hid}/cover.jpg"
        self.throttle.call(
            lambda: media.download(client, hl.cover_url, self.archive_dir / cover_rel, None)
        )
        items: list[HighlightItem] = []
        for i, item in enumerate(self.throttle.iter(hl.get_items()), start=1):
            is_video = item.is_video
            url = item.video_url if is_video else item.url
            if not url:
                log.error("media_url_missing", highlight=hid, index=i)
                continue
            rel = f"media/hl/{hid}/{i:03d}.{'mp4' if is_video else 'jpg'}"
            taken = item.date_utc.replace(tzinfo=timezone.utc)
            self.throttle.call(partial(media.download, client, url, self.archive_dir / rel, taken))
            items.append(
                HighlightItem(
                    kind="video" if is_video else "image",
                    local_path=rel,
                    taken_at=taken,
                    width=1080,  # ponytail: story items don't expose dims publicly; 9:16 assumed
                    height=1920,
                    duration=None,
                )
            )
        return Highlight(
            id=hid,
            title=hl.title,
            cover=FileRef(local_path=cover_rel, remote_url=hl.cover_url),
            items=items,
        )
