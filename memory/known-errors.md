# Known Errors, Gotchas & API Limitations

Seeded from project scoping — these are anticipated, not yet all observed. Update with
real observations as they happen. **Read this before debugging anything.**

Severity: 🔴 breaks the run · 🟠 silent data loss · 🟡 annoyance · ⚪ expected behavior

---

## Instagram API / scraping

### 🔴 KE-001 — 401 on highlights/comments means the session died, not that the data is gone
The most confusing failure mode. Public posts keep downloading fine while highlights and
comments start 401ing, because they're the only calls that need auth. Symptom looks like
"highlights broke"; cause is "session expired."
**Handle:** detect 401 on authenticated endpoints, halt cleanly, surface *"Your session
expired — re-import it."* Never retry a dead session in a loop. **Never fall back to a
password prompt** (D-009).

### 🔴 KE-002 — Instagram will ban the burner. This is expected.
Not a bug. Design for it: the burner is consumable. What *is* a bug is losing work when
it happens — see KE-004.
**Mitigation:** warm the account up before first use (profile pic, a few follows, some
normal browsing over a few days). A day-old account with zero activity that immediately
starts pulling GraphQL is an obvious bot and gets flagged fast.

### 🔴 KE-003 — 429 rate limiting, and the metronome tell
Fixed-interval requests are a bot signature even at a polite rate. Randomize the sleep.
**Handle:** exponential backoff with jitter; hard per-session request ceiling; stop
voluntarily before Instagram stops you.

### 🟠 KE-004 — An interrupted run must never lose or duplicate work
Given KE-002 and KE-003, interruption is the *normal* path. Any code that assumes a run
completes is wrong.
**Handle:** write to `progress.json` **after each post is fully committed** (media on
disk *and* metadata recorded), never before. Set `capture_stats.incomplete: true` and
clear it only on clean completion.

### 🟡 KE-005 — Password login trips the checkpoint challenge
Fresh API clients doing password auth routinely hit Instagram's 2FA/checkpoint wall.
This is the practical reason (on top of the security one) that D-009 exists. If you find
yourself building a challenge-handling flow, **stop — you've violated D-009.**

### ⚪ KE-006 — Private profiles
Out of scope. Detect `is_private` and refuse early with a clear message, rather than
half-failing deep into a run.

### 🔴 KE-025 — 403 on graphql/query with a *valid* session (observed 2026-07-17)
`test_login()` succeeds (it uses the iPhone API) but `https://www.instagram.com/graphql/query`
returns 403. This is the bot-wall, **not** a dead session (that's a 401 — KE-001). Two causes
seen: (1) the session was imported with only a `sessionid` cookie — graphql wants the full jar
(`csrftoken`, `ds_user_id`, `mid`); (2) client user-agent doesn't match the browser that minted
the cookies (Instaloader's default UA is Chrome).
**Handle:** import the full cookie jar (`session.parse_pasted_cookies` accepts a whole cookie
string); pin the loader UA to Firefox (`session.FIREFOX_UA`); surface a fix-naming message, not
the raw 403. If it persists: the account is flagged — warm it up and wait hours, not minutes.

**Update 2026-07-17:** diagnosed a case where the 403 is NONE of the above — anonymous requests
403 identically (even `Profile.from_username("instagram")`), so it's client-level, not
account/cookies. Root cause: Instagram deprecated the graphql doc_ids that Instaloader ≤4.15.2
uses (June 2026); everyone on the library is hit. Fix is upstream in PR
instaloader/instaloader#2706 (doc_id migration + X-CSRFToken header), unmerged and unreleased as
of today; reports of mixed results on profile queries. **Action:** `pip install -U instaloader`
periodically and retest with `scratchpad/diag_403.py`-style probe (session-valid + anonymous
fetch). Nothing in our code to fix — D-001 "reconsider if Instaloader stops tracking Instagram's
API changes" is on watch, not triggered; the project is actively working the fix.

**Update 2026-07-17 (later):** installed the PR from the official repo's PR ref —
`pip install --force-reinstall --no-deps "git+https://github.com/instaloader/instaloader.git@refs/pull/2706/head"`
— and 403s stopped: profile fetch, post enumeration, and media URLs all work. The PR diff was
verified to touch only `instaloadercontext.py`/`structures.py` (no deps/packaging). **Caveats:**
the venv now runs unreleased code that still reports version 4.15.2, and reinstalling deps
clobbers it back to the broken PyPI build — re-run the command above after any `pip install -e`.
Under the PR's converted response shape, `_full_metadata` no longer carries `dimensions` (our
code falls back to 1080×1350) and no music candidate path matched on the probe post — watch for
`music_shape_shifted` warnings once real reels with music go through (KE-008). Switch back to
plain `pip install -U instaloader` once upstream ships a release containing the fix.

**Update 2026-07-17 (music restored):** the PR's converted graphql shape carries NO music block
and no dimensions — confirmed by dumping a real reel's `_full_metadata` (bare legacy keys only).
The mobile v1 API (`post._iphone_struct`, i.instagram.com) is unaffected by the graphql
deprecation and carries `clips_metadata`/`music_metadata` in the shapes CANDIDATE_PATHS already
probe. `music.extract_from_post` and `dimensions_from_post` now fall back to it. Archives
captured while extraction was broken can be repaired in place with
`scripts/backfill_music.py <username>` (metadata + audio files, no media re-downloads).

### 🔴 KE-026 — "Guaranteed" Instaloader fields aren't; a field crash killed the job thread silently (observed 2026-07-17)
Under the PR-2706 response conversion, `post.video_duration` raised `KeyError` (the converted
shape drops fields that used to always exist). Worse: the job thread had no catch-all, so it
died mid-run while the UI kept showing FETCHING with a frozen progress bar — a silent hang from
the user's perspective.
**Handle:** every Instaloader field that isn't structurally essential goes through
`fetcher.opt()` (missing → `None`, recorded as a gap). The job thread's `run()` has a final
`except Exception` that sets FAILED with a user-facing message and logs the traceback. A stuck
progress bar now always has a state transition explaining it.

---

## Music (the fragile feature — expect breakage here first)

### 🔴 KE-007 — `post._full_metadata` is unofficial and *will* break
The music block is not in Instaloader's public API. We reach into the raw dict. When
Instagram reshuffles its response shape, **this is the first thing that breaks.**
**Handle:** all raw-dict access is confined to `music.py` (D-006). Wrap every key access
defensively — a missing key must yield `music: null`, never a `KeyError` that kills the
run. **A music failure must never abort a download.**

### 🟠 KE-008 — The music block moves around between response shapes
It has been seen under `clips_music_attribution_info` (reels) and `music_info` (photo
posts with a sticker), and the nesting is not stable.
**Handle:** probe a list of candidate paths in order, take the first hit, log which path
matched. When *none* match on a post that visibly has music, log it loudly — that's the
early warning that Instagram changed something.

### 🟠 KE-009 — Photo audio files are often simply not available
Not a bug in our code. Sometimes the music block carries an asset URL; sometimes it
carries only identifiers. Varies by post, by track, by month.
**Handle:** capture the metadata regardless; set `audio_local_path: null`; increment
`capture_stats.audio_files_missing`. **Do not retry, do not error, do not warn per-post.**
Report the count once at the end so it doesn't look like a failure.

### 🟠 KE-010 — `music: null` vs `audio_local_path: null` are different states
Conflating them is the most likely *logic* bug in this project.
- `music: null` → post had no music.
- `music.audio_local_path: null` → post had music, we couldn't get the file.
The viewer shows the song name in the second case and hides the play control. Contract
tests must cover both.

### 🟡 KE-011 — Original-audio reels have no title/artist
When a creator uses their own audio, there's no track metadata — often just
"Original audio · <username>". Don't render an empty song bar; either show the original-
audio label or omit the bar entirely.

---

## Media & quality

### 🟠 KE-012 — Grabbing the wrong entry from `display_resources` / `video_versions`
These arrays are **not reliably sorted** in the order you assume. Taking `[0]` is a
silent quality bug — you get a 640px thumbnail and never notice until you zoom in.
**Handle:** never index blindly. Select by `max()` on width/height (and bitrate for
video). Assert the chosen resolution meets the expected ceiling; log if it doesn't.

### 🟠 KE-013 — Any image library in the download path destroys quality
Opening a JPEG with Pillow and saving it re-encodes it. Zero benefit, permanent loss.
**Handle:** the download path streams bytes to disk. If you see `Image.open` anywhere
under `media.py`, that's a P0 bug (D-004).

### 🟠 KE-014 — ffmpeg without `-c copy` transcodes
Same class of bug, for audio. `ffmpeg -i in.mp4 out.m4a` **re-encodes**.
**Handle:** always `-vn -acodec copy`. Verify the output codec matches the input.

### 🟡 KE-015 — CDN URLs expire
`scontent.cdninstagram.com` URLs are signed and time-limited (hours). A `remote_url`
stored in `profile.json` will be dead later — it's kept for provenance, **not** for
re-fetching. Don't build anything that assumes it still resolves. Don't let the viewer
fall back to it (the viewer makes no network calls at all — D-003).

### 🟡 KE-016 — Filename collisions in carousels
Carousel items can share a base name. Use `<shortcode>/001.jpg`, `002.jpg` — index
within the post directory. Never flatten media into one folder (that's the wfdownloader
failure we exist to fix).

---

## Viewer & data contract

### 🟠 KE-017 — `comments: []` is ambiguous without `comments_captured`
Empty list + `comments_captured: false` = we didn't fetch them. Empty + `true` = there
genuinely are none. The viewer must render these differently ("Comments not captured in
this snapshot" vs "No comments"). Conflating them is a lie to the user about what's in
their archive.

### 🟠 KE-018 — Absolute paths make archives unmovable
Every `local_path` is **relative to the archive root**. An absolute path breaks the
moment the user moves the folder or opens it on another machine. Contract test this.

### 🟡 KE-019 — Single images are not a special case
`media` is always a list. A single photo is a carousel of length 1. If you write
`if post.type == "image": use post.media` anywhere, you've created a branch that will
diverge. Uniform handling kills a whole class of bugs.

### 🟡 KE-020 — Emoji, RTL text, and newlines in captions
Captions carry emoji, right-to-left scripts, and hard line breaks. Preserve verbatim;
UTF-8 everywhere; render with `white-space: pre-line`. Don't strip, don't normalize.

### 🟡 KE-021 — `file://` and CORS
Opening the viewer directly off disk can block `fetch('profile.json')` under some
browsers' file:// policy. This is why the viewer is served by the local FastAPI server.
If you add a "just open the HTML" path, test it — you may need to inline the JSON.

---

## Packaging

### 🟡 KE-022 — PyInstaller and ffmpeg
The ffmpeg binary must be explicitly bundled and located at runtime via
`sys._MEIPASS`, not assumed to be on `PATH`. The target machine has no ffmpeg.

### 🟡 KE-023 — Bind to `127.0.0.1`, never `0.0.0.0`
`0.0.0.0` quietly turns a personal local tool into an unauthenticated service exposed to
the whole LAN. There is no auth on this server because there was never supposed to be
anyone else on it.

### 🟡 KE-024 — Browser cookie-jar paths differ per OS and per browser
Firefox, Chrome, and Chromium-variants store cookies in different places and formats,
and OS keychain encryption (macOS especially) complicates reads. Expect this to be
fiddly. Fail with a clear, actionable message naming the browser and the path tried —
never a raw stack trace.
