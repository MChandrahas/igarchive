# igarchive

A local, single-launch desktop tool that downloads a **public** Instagram profile in
full — media *and* the metadata other downloaders throw away (captions, comments,
highlights, song attribution) — and ships an offline viewer that reconstructs the
profile: grid, carousels, reels, highlight rings, comment threads, and music (including
the creator's chosen song snippet, looped, exactly as Instagram plays it).

The archive is self-contained and future-proof: `profile.json` is human-readable, media
is byte-for-byte original, and the viewer is plain HTML that opens in any browser with
the app long gone.

> **Personal, local archiving only.** No hosting, no redistribution. Use a **burner**
> Instagram account for the session — scraping gets accounts banned; that is the
> expected end-state of the burner and must never be your main account.

---

## Download

Grab the latest **`igarchive.exe`** (Windows, single file — ffmpeg and the viewer are
bundled) from the [**Releases page**](https://github.com/MChandrahas/igarchive/releases/latest).
Nothing to install; see [Quick start](#quick-start-the-packaged-app) below.

To run from source instead (any OS), see [Developer setup](#developer-setup-running-from-source).

---

## Table of contents

- [Quick start (the packaged app)](#quick-start-the-packaged-app)
- [Using the app](#using-the-app)
- [Where your data lives](#where-your-data-lives)
- [Sharing & moving archives to another computer](#sharing--moving-archives-to-another-computer)
- [Maintenance scripts (music, covers)](#maintenance-scripts-music-covers)
- [Developer setup (running from source)](#developer-setup-running-from-source)
- [Building the exe](#building-the-exe)
- [Troubleshooting](#troubleshooting)
- [Future-proofing: when Instagram breaks it](#future-proofing-when-instagram-breaks-it)
- [Architecture & further reading](#architecture--further-reading)

---

## Quick start (the packaged app)

*(Windows. For macOS/Linux, [run from source](#developer-setup-running-from-source).)*

1. **Double-click `igarchive.exe`.** A local server starts and your browser opens to the
   control page automatically. No terminal, no Python, no ffmpeg install required — it's
   all bundled.
2. **Import a session** (one-time): log into Instagram in **Firefox** with a *burner*
   account, then click **Import from Firefox**. (Any browser works via the paste option —
   see [Session import](#1-session).)
3. **Type a public profile's username** (just the handle, not a URL), pick options, click
   **Download profile**.
4. When it finishes, the archive appears under **Archives** — click it to browse offline.
5. **Click "Quit igarchive"** when done. Closing only the browser leaves the server
   running in the background (visible in Task Manager) — Quit stops it completely.

> **First-launch Windows SmartScreen warning** is normal for a self-built, unsigned exe:
> *More info → Run anyway.*

---

## Using the app

### 1. Session

Authentication is by importing an existing browser cookie jar. **The app never asks for,
sees, or stores a password.**

- **Import from Firefox** — reads the Instagram cookies from your default Firefox profile.
  Most reliable, because it brings the *full* cookie jar.
- **Paste cookies** (any browser) — open DevTools → Network tab → click any
  `instagram.com` request → Request Headers → copy the entire `Cookie` value and paste it.
  A bare `sessionid` sometimes works but gets blocked (403) more often — paste the whole
  string.

The session is saved to `archives/.session.json` and reused on the next launch. If it
dies, the app says *"re-import it"* — it never falls back to a password prompt.

### 2. Download options

| Option | Default | Notes |
|---|---|---|
| Highlights | ✅ on | Covers + every story item. |
| Comments | ☐ off | One throttled request **per post** — slow. Off keeps the common run fast. |

### 3. What gets captured

All posts (newest-first, like the grid), carousels (order preserved), reels (with the
creator's cover image), captions, likes, view counts, timestamps, highlights, song
title/artist, and — where obtainable — the audio file and the creator's snippet timing.
Comments only when you tick the box.

### 4. Resumability (important)

Every run is **resumable**. The tool deliberately stops itself after **800 requests** in
one session to protect the account, and it may be interrupted by rate-limiting or a ban.
When that happens it stops cleanly — just click **Download profile** for the same username
again and it continues where it left off. **Nothing re-downloads.**

- Progress lives in `archives/<username>/progress.json`.
- A completed post is never re-fetched. **New** posts/highlights are picked up on re-runs
  (this is also how you update an archive later — just download the same profile again).
- Known gap: new items added to an **existing** highlight aren't re-checked (brand-new
  highlights are). Ask if you need this.

---

## Where your data lives

```
igarchive.exe
archives/
├── .session.json            ← your login cookie jar (SENSITIVE — see Sharing)
└── <username>/
    ├── profile.json         ← THE archive: all captions, comments, music metadata, paths
    ├── progress.json        ← resume state
    └── media/
        ├── avatar.jpg
        ├── <shortcode>/
        │   ├── 001.jpg / 001.mp4      ← post media, byte-for-byte original
        │   ├── 001.m4a               ← reel audio (stream-copied from the mp4)
        │   ├── 001_cover.jpg         ← creator's reel cover
        │   └── music.m4a             ← photo-post song file (full track)
        └── hl/<id>/...              ← highlight covers + items
```

**Music specifically** (a common question):
- **Audio files** — photo-post songs are at `media/<shortcode>/music.m4a`; reel audio is
  the `media/<shortcode>/NNN.m4a` extracted from the video.
- **Metadata that drives playback** — in `profile.json`, each post's `music` block:
  `title`, `artist`, `audio_local_path`, and `snippet_start_ms` / `snippet_duration_ms`
  (the creator's chosen segment; the viewer seeks there and loops it, matching Instagram).

All paths in `profile.json` are **relative to the archive root**, which is what makes an
archive movable.

---

## Sharing & moving archives to another computer

**Safe to share:** a single profile folder, e.g. `archives/sii_shore/`. It's media +
data only, and the viewer makes **zero network requests** — nobody can download or
impersonate anything with it.

**Do NOT share the whole `archives/` folder** — it contains `archives/.session.json`,
your burner's live login. Anyone with that file could act as the account until it expires.

**To view an archive on another computer:**

1. Zip the profile folder (`archives/sii_shore/`).
2. On the other machine, place `igarchive.exe` anywhere, and unzip so you have an
   `archives/` folder **right next to the exe**:
   ```
   igarchive.exe
   archives/
     └── <username>/
   ```
3. Double-click the exe → click the archive → browse. **No internet, Python, or ffmpeg
   needed** on that machine — everything is in the exe and the archive.

> The **layout is the only requirement** — the exe looks for `archives/` beside itself.
> Browsing needs no session. Downloading *more* on that machine would need a fresh session
> import there.

---

## Maintenance scripts (music, covers)

These repair or enrich an existing archive without re-downloading media. Run them from
the project root, using the venv's Python. Both are **resumable** and print one line per
post.

```bash
# Fill in song metadata + snippet timing + audio files for posts that lack them
.venv/Scripts/python.exe scripts/backfill_music.py <username>

# Fetch creator-chosen reel cover images for existing reels
.venv/Scripts/python.exe scripts/backfill_covers.py <username>
```

When to use them: after downloading with an older build, or if songs/covers are missing.
Future downloads capture music, snippets, and covers automatically — these are only for
catching up existing archives. They need a valid session (import one in the app first).

---

## Developer setup (running from source)

**Requirements:** Python 3.11+, and ffmpeg for reel audio (bundled in the exe, but needed
when running from source).

```bash
# Windows note: `python`/`py` may not be on PATH (the Microsoft Store alias intercepts).
# Create the venv with the real interpreter, then use .venv\Scripts\python.exe for everything.
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"

# Reinstall the patched Instaloader (see Future-proofing — a plain reinstall breaks fetching):
.venv\Scripts\pip install --force-reinstall --no-deps "git+https://github.com/instaloader/instaloader.git@refs/pull/2706/head"

# Run in dev (browser opens automatically)
.venv\Scripts\python -m igarchive.launcher --dev

# Serve an existing archive's viewer only, no network features
.venv\Scripts\python -m igarchive.launcher --serve-only archives/<username>
```

**ffmpeg on Windows:** `winget install Gyan.FFmpeg`. A shell opened *before* the install
won't have it on PATH; open a new shell, or the app also falls back to winget's
`...\WinGet\Links\ffmpeg.exe`.

### Tests & checks

```bash
.venv\Scripts\python -m pytest            # full suite (fixtures only — never hits Instagram)
.venv\Scripts\python -m pytest -m contract  # the profile.json contract gate
.venv\Scripts\mypy src\                    # strict typing
.venv\Scripts\ruff check . && .venv\Scripts\ruff format --check .
```

`pytest -m contract` is the gate between the fetcher and viewer halves. If `profile.json`
changes shape, it fails first, on purpose.

---

## Building the exe

```bash
# ffmpeg must be findable on PATH so it can be bundled:
# PowerShell: $env:PATH = "$env:LOCALAPPDATA\Microsoft\WinGet\Links;$env:PATH"
.venv\Scripts\python build.py
```

Produces `dist/igarchive.exe` (~108 MB, single file, ffmpeg + viewer bundled). Copy it
next to an `archives/` folder to run.

> The exe **freezes in whatever Instaloader is installed** — including the PR patch. When
> Instaloader ships the official fix (see below), reinstall it and rebuild to pick it up.

---

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| **Stuck on "Loading archive…"** | Stale cached JS, or a viewer error. Hard-refresh (**Ctrl+Shift+R**). The page now shows the actual error instead of hanging; if it names a file/line, report it. |
| **Viewer shows old data** (missing highlights/songs after an update) | Cached `profile.json`. Hard-refresh once. The server now sends no-cache headers, so plain refreshes work afterward. |
| **"Instagram blocked the request (403)"** | Bot-wall, not a dead session. Re-import the **full** cookie jar; wait a few hours; and check for an Instaloader update. See [Future-proofing](#future-proofing-when-instagram-breaks-it). |
| **"Your session expired — re-import it"** | A real 401. Log into Instagram in your browser again and re-import. Never a password. |
| **Download bar stuck at 100%** | Not stuck — it's downloading highlights (the bar only tracks posts). Large highlights take minutes at the safe request rate. |
| **Run crashed mid-way** | Completed posts are safe. The UI shows FAILED with the reason; just download the same profile again to resume. |
| **Reel shows a black/blank tile** | Its cover wasn't captured (e.g. a since-deleted post). Run `backfill_covers.py`, or it falls back to the video's first frame in a real browser. |
| **Song/cover missing on some posts** | Original-audio reels and older metadata shapes may lack timing; deleted posts can't be re-fetched. Run the backfill scripts for the rest. |
| **App still in Task Manager after closing** | You closed the browser, not the app. Use the **Quit igarchive** button on the control page. |
| **SmartScreen blocks the exe** | Expected for an unsigned self-built exe: *More info → Run anyway.* |
| **`python` not found / opens Microsoft Store** | The Store alias. Use `.venv\Scripts\python.exe`, or disable the alias in Settings → Apps → Advanced app settings → App execution aliases. |

**Deeper debugging:** the server logs every download (with selected resolution) and every
music-path match to the console. A `music_shape_shifted` warning is the early signal that
Instagram changed its response shape (see below). `memory/known-errors.md` documents every
known trap in detail (KE-001 … KE-026).

---

## Future-proofing: when Instagram breaks it

Instagram periodically changes its private API, which breaks Instaloader (the scraper this
tool builds on) for **everyone** until Instaloader ships a fix. This is the single most
likely thing to break. Symptoms: `403 Forbidden on graphql/query`, or
`Fetching Post metadata failed`, on downloads that used to work — even though your session
is valid.

**Current state (as of this build):** a fix for the mid-2026 breakage is in Instaloader
**PR #2706**, not yet in a released version, so this build installs it directly from the
PR. That's why the dev-setup reinstall command points at
`refs/pull/2706/head` and why a plain `pip install instaloader` will re-break fetching.

**When it breaks again:**

1. **Check for an Instaloader release first** — the maintainers usually ship these fixes
   within days to weeks:
   ```bash
   .venv\Scripts\pip install -U instaloader
   ```
2. **Retest** with the diagnostic pattern: confirm your session is valid *and* that a
   simple anonymous fetch works. If even `instaloader.Profile.from_username(ctx, "instagram")`
   returns 403, it's the library/API, not your account.
3. If a fix exists only as an unmerged PR, install it by ref (as the current build does):
   ```bash
   .venv\Scripts\pip install --force-reinstall --no-deps "git+https://github.com/instaloader/instaloader.git@refs/pull/<NUMBER>/head"
   ```
   Verify the PR only touches Instaloader's own source before trusting it with your session.
4. **Rebuild the exe** (`python build.py`) to bake in the updated library.

**Music/metadata shape shifts** are contained to `src/igarchive/music.py` by design. If
songs stop being detected, the log prints `music_shape_shifted`; add the new candidate
path to `CANDIDATE_PATHS` there — a one-file fix. All raw-metadata access is quarantined
in that module for exactly this reason.

**The archives you already have are never at risk** from any of this. Instagram breaking
the scraper only affects *new* downloads; existing `profile.json` + `media/` keep working
in the viewer forever.

---

## Architecture & further reading

The fetcher half and the viewer half communicate **only** through `profile.json` — the
viewer never calls Instagram, never imports Python, never knows the fetcher exists. This
hard contract is what makes archives outlive the tool.

- `CLAUDE.md` — architecture map, module responsibilities, hard constraints.
- `docs/project-overview.md` — personas, features, the "music problem", success metrics.
- `memory/decisions.md` — why the architecture is the way it is (read before changing it).
- `memory/known-errors.md` — every known trap and gotcha, with fixes (KE-001 … KE-026).
- `skills/guidelines.md` — coding standards and the contract discipline.

**Hard rules** (violating any is a bug, not a preference): local-only (`127.0.0.1`); never
handle a password; never re-encode media (ffmpeg `-c copy` only); always rate-limit and
stay resumable; the viewer never touches the network.

---

## License

[MIT](LICENSE) — free to use, modify, and distribute. For **personal, local archiving**;
do not use it to redistribute or re-host downloaded content.
