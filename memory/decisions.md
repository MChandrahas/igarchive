# Decisions

Architectural decisions settled during project scoping. Each records **what was
decided, why, what was rejected, and what would make us reconsider.**

Read this before proposing an architectural change. Most "obvious improvements" are
listed here as already-rejected alternatives, with the reason.

---

## D-001 — Build on Instaloader, not wfdownloader

**Decision:** Use Instaloader as the scraping engine. Do not wrap, drive, or depend on
wfdownloader.

**Why:** wfdownloader is a closed GUI app — it can't be bundled, can't be driven
programmatically from our launcher, and can't be extended. More importantly, it buys us
*nothing on quality*: it hits the same Instagram CDN URLs and saves the same bytes any
other tool does. What it lacks isn't download capability, it's **metadata capture** —
comments, highlights, and music were never in its output because it only ever saves
media files. You cannot organize your way to data that was never downloaded.

Instaloader already handles posts, carousels, reels, stories, highlights, captions,
comments, likes, and timestamps, and emits a JSON sidecar per post.

**Rejected:** Wrapping wfdownloader; writing a scraper from scratch (months of
re-solving Instagram's pagination and auth for no gain).

**Reconsider if:** Instaloader is abandoned and stops tracking Instagram's API changes.

---

## D-002 — Instaloader as a *library*, never the CLI

**Decision:** `import instaloader`. Never `subprocess.run(["instaloader", ...])`.

**Why:** This is the decision that makes the music feature possible at all. The CLI
gives you files on disk and a curated JSON sidecar. The **library** gives you `Post`
objects and, critically, access to the raw GraphQL response dict. **The music block —
song title, artist, audio ID — is not exposed through Instaloader's public API.** It
exists only in the raw metadata. Shelling out to the CLI throws it away permanently.

**Consequence:** we depend on an unofficial access path. See D-006.

**Rejected:** CLI + parsing the sidecars (no music data, ever).

---

## D-003 — `profile.json` is the contract between the two halves

**Decision:** The fetcher's only output is `profile.json` + a `media/` folder. The
viewer's only input is `profile.json` + `media/`. Neither half knows the other exists.

**Why:** These two halves change for completely different reasons — the fetcher changes
when Instagram changes, the viewer changes when we want a nicer UI. A hard contract
between them means Instagram breaking the scraper never breaks the archives you already
have, and redesigning the viewer never risks the download logic. It also means the
**archive outlives the tool**: `profile.json` is human-readable, and the viewer is
plain HTML that will still open in ten years.

Pydantic models in `schema.py` are the single source of truth. Contract tests
(`pytest -m contract`) gate every commit.

**Corollary:** the viewer makes **zero network requests**. If it fetches anything, that's
a bug, not a feature.

---

## D-004 — Maximum quality means *refusing to touch the file*

**Decision:** Stream bytes to disk verbatim. Never open, decode, or re-save media.
ffmpeg runs with `-c copy` and nothing else.

**Why:** The framing question "how do we download without losing quality?" has a
counter-intuitive answer: **there is no original to preserve.** Instagram re-encodes on
upload and destroys what the poster sent. What the CDN serves *is* the best that exists,
for us and for every other tool. So "no quality loss" cannot mean recovering
something — it can only mean **not degrading what we're handed.**

Concretely:
- Photos: take the **last** entry of `display_resources` (typically 1080px — the hard
  ceiling for feed photos; nothing gets more).
- Videos: take the highest resolution/bitrate entry of `video_versions`.
- Stream the HTTP response straight to disk. **No Pillow. No re-save.** Opening a JPEG
  and writing it back out loses quality for zero benefit — this is the single most
  common way these tools silently wreck files.
- ffmpeg only stream-copies the AAC track out of a reel mp4. Bit-identical audio.
- Restore file mtime to the post date so the folder sorts correctly outside the app.

**Rejected:** Any image library in the download path. Any "quality" or "resize" option.
Any upscaling. If someone proposes an enhancement feature, the answer is no — it's a
different product.

---

## D-005 — Authenticated (burner account), not anonymous

**Decision:** The tool authenticates via a session imported from a burner account.

**Why:** Highlights and comments were both on the original must-have list, and **neither
is reachable anonymously.** This is structural, not a limitation of our tooling:

- A public profile page ships posts/captions/media in an embedded JSON blob — that's
  public because the page has to be shareable and indexable.
- **Highlights are fetched by a separate GraphQL call that requires a session cookie
  and an authenticated app context.** Logged out, it doesn't return a reduced version —
  it returns nothing. The highlight *covers* come down with the profile blob (which is
  why they render in incognito), but clicking one hits a login wall. The story items
  were never sent.
- Comments are the same shape: a few may ride along in the initial blob, but paginating
  the full thread is an authenticated query.

There is no "logged-out but complete" mode to unlock. The only workarounds — burner
pools, residential proxies, paid scraping APIs — are all the same trick (*be logged in,
but look like many different people*), just with more moving parts or a bill.

**Cost accepted:** the account will eventually be banned. That's the expected end state.

**Rejected:** Anonymous-only (drops highlights and comments — over half the point of the
project); proxy pools and paid scraping APIs (complexity and cost for a personal tool).

---

## D-006 — Isolate the music extraction in exactly one function

**Decision:** All raw-metadata access lives in `music.py`. Nowhere else.

**Why:** Reaching into `post._full_metadata` is a documented-but-unofficial path (see
D-002). It is **the most likely thing in the codebase to break** when Instagram
reshuffles its response shape. Containing it to one module means a break is a one-file
fix, and the rest of the codebase never learns to depend on raw dict access.

**Two different reliabilities, and the code must model both:**
- **Song metadata** (title/artist/ID) — reliable, for photos *and* reels. Always capture.
- **The audio file** — reels always (it's a stream inside the mp4). Photos
  *conditionally*: sometimes the music block carries an asset URL, sometimes only
  identifiers. Varies by post, by track, and by whatever Instagram changed last.

**Therefore:** `music: null` (no music) and `music.audio_local_path: null` (music, no
file) are **distinct states**. The viewer shows the song name in both cases and only
renders a play control when a file exists. Never crash, never show a dead player.

---

## D-007 — Comments are a toggle, default OFF

**Decision:** Comments capture is opt-in per run.

**Why:** Once authenticated, comments are free to *implement* — but expensive to *run*.
One request per post, aggressively throttled. A 200-post profile is minutes without
comments and a coffee break (or much longer) with them. Making it a toggle means the
common case stays fast and the completionist case is still available.

---

## D-008 — Resumability is a foundation, not a feature

**Decision:** `progress.json` records every shortcode already fetched. Every network
path is resumable from day one.

**Why:** Given D-005, **getting banned or throttled mid-run is the expected case, not
the exceptional one.** On a comment-heavy profile this is the difference between a
usable tool and a toy. Retrofitting resumability into a codebase that assumed
happy-path completion is a rewrite; designing for it costs almost nothing on day one.

Rate limiting is part of the same decision:
- **Randomized** sleeps, not fixed intervals. A metronome is a bot signature.
- Exponential backoff on 429.
- A hard per-session request ceiling — **stop voluntarily before Instagram stops you.**

---

## D-009 — Never handle passwords

**Decision:** Authentication is by importing an existing browser cookie jar. The app has
no password field, ever.

**Why:** Two reasons, both sufficient on their own.
1. **Security:** a local tool that stores Instagram credentials is a liability we have
   no reason to take on. If we never accept a password, we can never leak one.
2. **It works better.** Password logins from a fresh API client routinely trip
   Instagram's checkpoint challenge. A cookie jar from a browser that already logged in
   successfully looks like what it is — an existing, warmed session.

**Flow:** first run → "Log into Instagram in your browser, then click Import session."
Session dies → app catches the 401, says so plainly, offers re-import. It does **not**
ask for a password. Not as a fallback, not as an "advanced option."

---

## D-010 — Local-only, PyInstaller + browser UI

**Decision:** One double-clickable artifact. It starts a FastAPI server bound to
`127.0.0.1`, auto-opens the browser, and serves the UI there. No terminal, ever.

**Why:** The requirement was "a single launch thing rather than running commands." The
realistic options were PyInstaller + browser UI, or Tauri/Electron for a native window.
Tauri means maintaining **two runtimes** (a JS shell plus the Python core) for a purely
cosmetic gain — the user experience is identical. PyInstaller gets the same result for a
third of the work, and wrapping it in a native shell later is a **swap of the shell, not
a rewrite.**

Binding to `127.0.0.1` (never `0.0.0.0`) is what keeps "local tool" from silently
becoming "unauthenticated service on your LAN."

**A hosted version is explicitly out of scope.** Scraping arbitrary profiles on demand
as a service multiplies both the ban risk and the legal exposure. Keeping this a local,
personal archiving tool — no redistribution, no re-hosting — is what keeps the project
on solid ground, and it's a scope boundary, not a nag.
