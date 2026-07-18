# Project Overview — `igarchive`

## 1. Core purpose

Bulk Instagram downloaders solve half a problem. They get the pixels; they lose the
context. When you point wfdownloader at a profile you end up with a folder of
`2026-07-08_1.jpg` files — no captions, no comments, no highlights, no idea which
photo was part of which carousel, and no record of the song that was playing. The
archive is technically complete and practically useless.

`igarchive` treats an Instagram profile as a **structured document, not a pile of
files.** It captures media *and* the metadata that makes media legible, then renders
the whole thing back as a browsable offline profile: the grid, the carousels you can
swipe, the reels, the highlight rings, the comment threads, the song attribution.

**The success condition:** you open the archive a year later, on a machine with no
internet, and it feels like you're looking at the profile.

### What it is
- A local desktop tool. One double-click. No terminal.
- A faithful capturer: highest quality Instagram serves, byte-for-byte.
- A viewer that reconstructs the browsing experience offline.

### What it is not
- Not a hosted service. Not multi-user. Not a scraping API.
- Not a redistribution tool. Archives are personal and local.
- Not an enhancer. It does not upscale, sharpen, or re-encode anything.

---

## 2. User personas

**P1 — The Archivist (primary; this is the user we're building for)**
Wants a durable, complete, personal copy of a profile — their own, a friend's, an
artist's, a source's — because accounts get deleted, deactivated, and rug-pulled.
Cares about *completeness and fidelity*. Will accept a slow run if it means nothing is
missing. Frustrated that existing tools drop everything except the JPEGs.
→ Drives: metadata capture, resumability, quality guarantees, the highlights feature.

**P2 — The Researcher**
Studying a public account — a brand, a creator, a movement. Needs captions, comment
threads, timestamps, and song attribution because the *text and social layer* is the
actual data; the images are incidental. Will export to CSV/JSON downstream.
→ Drives: comments capture, the clean `profile.json` schema, machine-readable output.

**P3 — The Creator (secondary)**
Backing up their own account before a platform migration or a deletion. Wants their own
media at max quality and their own captions back.
→ Drives: quality fidelity, avatar/bio capture, the "this is my account" fast path.

**Explicit non-persona:** anyone who wants to re-publish, resell, or bulk-harvest other
people's content. The product must not make that easier, and the docs must not invite it.

---

## 3. Main features

### 3.1 Capture

| Feature | Status | Notes |
|---|---|---|
| Photos (single) | ✅ Core | Max resolution from `display_resources` |
| Carousels | ✅ Core | Order preserved; grouped as one post |
| Reels / videos | ✅ Core | Max resolution from `video_versions` |
| Captions | ✅ Core | Verbatim, including emoji and line breaks |
| Likes, view counts, timestamps | ✅ Core | |
| Profile: avatar, bio, name, counts | ✅ Core | |
| **Song title + artist** | ✅ Core | Photos **and** reels. See §3.2 |
| **Reel audio file** | ✅ Core | ffmpeg `-c copy` out of the mp4 |
| **Photo audio file** | ⚠️ Best-effort | Only when Instagram exposes a URL. See §3.2 |
| **Highlights** | ✅ Requires session | Covers + all items |
| **Comments + replies** | ✅ Requires session | **Toggle, default OFF** — slow |
| Stories (live, 24h) | ❌ Out of scope v1 | Ephemeral; different problem |
| Tagged posts | ❌ Out of scope v1 | |

### 3.2 The music problem, stated precisely

This is the feature no other tool has, and it has two halves that behave differently.

**Song metadata (title, artist, audio ID)** — reliably present in the post's raw
metadata for both photos and reels. We capture it always. The viewer's song bar is
populated for every post that had music.

**The audio file itself:**
- **Reels:** always obtainable. The audio is a stream inside the downloaded `.mp4`.
  ffmpeg stream-copies it out to `.m4a`. Lossless, always works.
- **Photos:** *conditional.* Sometimes the music block carries a direct asset URL;
  sometimes it carries only identifiers. It varies by post, by track, and by whatever
  Instagram last changed. We grab it opportunistically and record `audio_local_path:
  null` when it isn't there.

The viewer must degrade gracefully: **song name always shows; the play control only
appears when a file exists.** Never crash, never show a broken player.

### 3.3 Browse (the viewer)

- Profile header: avatar, name, bio, counts, plus an **archive provenance banner**
  (captured-at timestamp, source URL, what was and wasn't captured).
- Highlight rings, clickable, story-style playback.
- Post grid with type badges (carousel / reel) and a song tag on the tile.
- Post modal: carousel navigation, comment thread with replies, song bar, likes,
  and a provenance strip (shortcode, original URL).
- Tabs: Posts / Reels / Highlights.
- Fully offline. No network requests, ever. If the viewer makes an HTTP call, it's a bug.

### 3.4 Run

- Double-click → local server starts → browser opens → username box → **Download profile**.
- Progress: per-post, with a live count and a visible rate-limit pause indicator.
- Resumable: kill it mid-run, relaunch, it continues. Nothing re-downloads.
- Session import UI: "log into Instagram in your browser, then click Import session."
  Never a password field.

---

## 4. Technical stack assumptions

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Instaloader is Python; no reason to split runtimes |
| Scraper | **Instaloader, as a library** | Only path to the raw metadata dict where music lives. The CLI discards it. |
| HTTP | httpx (streaming) | Byte-for-byte downloads without buffering whole files |
| Schema | Pydantic v2 | `profile.json` is a contract; enforce it |
| Server | FastAPI + Uvicorn, bound to `127.0.0.1` | Local only; never exposed |
| Media | ffmpeg, `-c copy` **only** | Stream-copy; any transcode is a quality bug |
| Viewer | Plain HTML/CSS/JS, no build step | Portable, archival, still opens in 10 years |
| Packaging | PyInstaller | One artifact; no Python install required on the target machine |

**Rejected:** Electron/Tauri (two runtimes for a cosmetic gain — revisit only if a
native window becomes a real requirement); the Instaloader CLI (loses music metadata);
any image library in the download path (silent quality loss).

---

## 5. Data contract — `profile.json`

The single source of truth. Fetcher writes it, viewer reads it, nothing else crosses
the boundary.

```jsonc
{
  "schema_version": 1,
  "captured_at": "2026-07-12T14:22:03Z",
  "source_url": "https://instagram.com/<username>",
  "capture_options": {
    "authenticated": true,
    "comments": false,
    "highlights": true
  },
  "capture_stats": {
    "posts_captured": 142,
    "highlights_captured": 6,
    "comments_captured": 0,
    "audio_files_missing": 3,      // photo posts whose music had no URL
    "incomplete": false             // true if the run was interrupted
  },

  "profile": {
    "username": "mara.fjord",
    "full_name": "Mara Fjordheim",
    "biography": "Landscape & film photographer...",
    "external_url": "https://maravisuals.example",
    "followers": 38400,
    "following": 612,
    "posts_count": 142,
    "is_verified": true,
    "is_private": false,
    "avatar": { "local_path": "media/avatar.jpg", "remote_url": "https://..." }
  },

  "highlights": [
    {
      "id": "17901234567890123",
      "title": "Iceland '25",
      "cover": { "local_path": "media/hl/17901.../cover.jpg" },
      "items": [
        {
          "kind": "image",              // image | video
          "local_path": "media/hl/17901.../001.jpg",
          "taken_at": "2025-11-02T09:14:00Z",
          "width": 1080, "height": 1920,
          "duration": null,
          "audio_local_path": null
        }
      ]
    }
  ],

  "posts": [
    {
      "shortcode": "C9xR2vLpQ",
      "type": "carousel",              // image | carousel | reel
      "taken_at": "2026-07-08T07:14:00Z",
      "caption": "Blue hour over Vestrahorn...",
      "likes": 4218,
      "views": null,                   // reels only
      "location": null,
      "source_url": "https://instagram.com/p/C9xR2vLpQ",

      "media": [
        {
          "kind": "image",
          "local_path": "media/C9xR2vLpQ/001.jpg",
          "remote_url": "https://scontent...",
          "width": 1080, "height": 1350,
          "duration": null,
          "audio_local_path": null     // reels: "media/<sc>/001.m4a"
        }
      ],

      "music": {                        // null when the post had no music
        "title": "Holocene",
        "artist": "Bon Iver",
        "audio_id": "aud_88213",
        "audio_local_path": null        // null when IG gave no URL — viewer hides play
      },

      "comments_captured": false,       // distinguishes "none" from "not fetched"
      "comments": [
        {
          "username": "nord.light",
          "text": "This is unreal 😍 what lens?",
          "created_at": "2026-07-08T08:02:00Z",
          "likes": 42,
          "replies": [
            { "username": "mara.fjord", "text": "24mm, 4s exposure",
              "created_at": "2026-07-08T09:10:00Z", "likes": 11 }
          ]
        }
      ]
    }
  ]
}
```

**Schema invariants (enforced by contract tests):**
- `media` is always a list, even for a single image. A carousel is not a special case;
  a single photo is a carousel of length 1. This kills an entire class of branching bugs.
- `music: null` means *no music on this post*. `music.audio_local_path: null` means
  *there was music, but we could not get the file*. These are different states and the
  viewer renders them differently.
- `comments: []` + `comments_captured: false` means *we didn't fetch them*.
  `comments: []` + `comments_captured: true` means *there genuinely are none*.
  Never conflate these.
- Every `local_path` is relative to the archive root. Absolute paths make archives
  unmovable and are a bug.

---

## 6. Success metrics

**Fidelity (the headline metric)**
- **100%** of downloaded photos match the max entry in `display_resources`. Any file
  smaller than the largest available resolution is a P0 bug.
- **Byte-identical** media: hash the downloaded file against a fresh fetch of the same
  URL. Any difference means something re-encoded, which is a P0 bug.
- **≥95%** of posts with music carry correct title + artist.
- **100%** of reels with audio produce a valid `.m4a`.

**Completeness**
- A full run captures every post the profile grid shows. Zero silent skips — anything
  skipped appears in `capture_stats` and in the UI.
- Highlights: every highlight, every item.

**Resilience**
- A run killed at any point resumes with **zero** re-downloads.
- A 429 never loses work and never crashes the run.
- A dead session produces a clear "re-import your session" message, never a stack trace
  and never a password prompt.

**Experience**
- Zero terminal commands from download to browsing.
- Media-only run on a 200-post profile: **minutes**.
- Full run with comments: slow by design, but with an honest live ETA — the user is
  never left guessing whether it hung.

**Archival durability**
- The archive folder opens in a browser with the app deleted. `profile.json` is
  readable by a human in a text editor. The archive outlives the tool.
