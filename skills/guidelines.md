# Coding Guidelines

Repeatable standards for this codebase. These are **rules, not suggestions** — they
encode decisions from `memory/decisions.md` and traps from `memory/known-errors.md`. If
a rule seems arbitrary, the reason is in one of those files; read it before overriding.

---

## 0. The three rules that override everything

1. **Never degrade media.** No image library in the download path. ffmpeg with `-c copy`
   only. If a change could re-encode a byte, it's wrong.
2. **Never handle a password.** Sessions come from an imported cookie jar. No password
   field, no fallback, no "advanced option."
3. **The viewer never touches the network.** It reads `profile.json` and local files.
   Nothing else.

A PR that violates any of these is rejected regardless of what else it does.

---

## 1. The contract discipline

`schema.py` (Pydantic v2) is the **single source of truth** for `profile.json`.

- **Never hand-write a dict** that's destined for `profile.json`. Construct the Pydantic
  model, let it validate, serialize it. Hand-built dicts drift.
- **Never hand-parse `profile.json`** on the Python side. Load it through the model.
- Bump `schema_version` on any breaking shape change, and write a migration.
- `pytest -m contract` is the gate. Schema changes fail it first, **on purpose**. Don't
  route around it — update the tests deliberately.

**Golden-file test:** keep a checked-in `tests/fixtures/profile.golden.json` covering
every state combination — post with music + audio, post with music + no audio, post with
no music, carousel, reel, single image, comments captured, comments not captured,
highlight with video items. Any schema change must update this file consciously.

---

## 2. Two states that are not the same state

The most likely logic bug in this project. Model these explicitly, everywhere:

| State | Means | Viewer renders |
|---|---|---|
| `music: null` | No music on this post | No song bar |
| `music.audio_local_path: null` | Music, but no file obtainable | Song bar, **no play control** |
| `music.audio_local_path: "..."` | Music with audio | Song bar + play control |
| `comments: []`, `comments_captured: false` | Not fetched | *"Comments not captured in this snapshot"* |
| `comments: []`, `comments_captured: true` | Genuinely none | *"No comments"* |

Never collapse a "we didn't get it" into a "there isn't one." That's lying to the user
about the completeness of their archive, which is the one thing this tool exists to get
right.

---

## 3. Python standards

- Python 3.11+. **Full type hints, no exceptions.** `mypy` strict on `src/`.
- `ruff` for lint and format. No manual style debates.
- **Pathlib only.** No `os.path`, no string path concatenation.
- Dataclasses/Pydantic for anything structured. No bare dicts crossing a module boundary.
- Module boundaries from `CLAUDE.md` §2 are enforced. If `normalizer.py` starts making
  HTTP calls, the design has been violated.

### Error handling

- **Never bare `except:`.** Never `except Exception: pass`.
- Distinguish three failure classes and treat them differently:
  - **Fatal** (dead session, private profile, no disk space) → halt cleanly, clear
    message, preserve `progress.json`.
  - **Retryable** (429, timeout, 5xx) → backoff and retry.
  - **Degradable** (missing music block, missing audio URL) → record the gap in
    `capture_stats`, **continue the run.** A music failure must never abort a download.
- **User-facing errors name the fix.** *"Session expired — re-import it from your
  browser"*, not *"401 Unauthorized"*. Never surface a stack trace to the UI.

### Logging

- `structlog`, JSON to a file, human-readable to console.
- Log the **selected media resolution** on every download — this is the audit trail that
  proves KE-012 isn't silently happening.
- Log **which candidate path matched** in `music.py` — the early warning for KE-008.
- Never log cookies, session tokens, or anything from the cookie jar. Ever.

---

## 4. Network layer

Every outbound request goes through one wrapper in `fetcher.py`. No module makes a bare
HTTP call.

The wrapper is responsible for, in this order:
1. **Randomized sleep** before the request (jittered, never a fixed interval — KE-003).
2. **Per-session request ceiling** — refuse and stop cleanly when hit.
3. **Exponential backoff with jitter** on 429/5xx.
4. **401 → fatal**, not retryable (KE-001).
5. Logging.

```python
# The shape. Do not duplicate this logic anywhere else.
async def request(self, fn: Callable[[], T]) -> T:
    await self._throttle()          # jittered sleep + ceiling check
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except TooManyRequests:
            await self._backoff(attempt)
        except Unauthorized as e:
            raise SessionExpired(...) from e   # fatal, never retried
    raise RateLimitExhausted(...)
```

---

## 5. Media downloads — the quality-critical path

```python
# CORRECT — bytes to disk, untouched
async with client.stream("GET", url) as r:
    r.raise_for_status()
    with dest.open("wb") as f:
        async for chunk in r.aiter_bytes():
            f.write(chunk)
os.utime(dest, (taken_at_ts, taken_at_ts))   # restore mtime — KE-004 adjacent
```

```python
# WRONG — silently destroys quality (KE-013)
img = Image.open(BytesIO(response.content))
img.save(dest)
```

**Resolution selection — never index blindly (KE-012):**

```python
# CORRECT
best = max(display_resources, key=lambda r: r["config_width"] * r["config_height"])

# WRONG — these arrays are not reliably sorted
best = display_resources[-1]   # or [0]
```

Assert the selected resolution meets expectations and log it. A 640px file where 1080px
was available is a P0 bug that nobody notices for months.

**ffmpeg — stream-copy only (KE-014):**

```python
["ffmpeg", "-i", str(mp4), "-vn", "-acodec", "copy", "-y", str(m4a)]
#                            ^^^^^^^^^^^^^^^^^^^^^^ never omit
```

---

## 6. `music.py` — the quarantine zone

**All raw-metadata access lives here. Nowhere else.** This is the module most likely to
break when Instagram changes (KE-007), and containing it means a break is a one-file fix.

- Probe a **list of candidate paths** in order; take the first hit; log which matched.
- Every key access is defensive. A missing key yields `None`, never a `KeyError`.
- The module's public surface is exactly one function:
  `extract_music(raw: dict) -> Music | None`.
- **No other module imports `_full_metadata` or touches a raw dict.** If you need
  something from the raw response, add it to `music.py`'s extraction or open a new
  quarantined module — do not leak raw-dict access outward.

```python
CANDIDATE_PATHS = [
    ("clips_metadata", "music_info", "music_asset_info"),   # reels
    ("music_info", "music_asset_info"),                     # photo + sticker
    # add new paths here as Instagram shifts; never remove old ones
]
```

When *no* path matches on a post that visibly has music, **log loudly.** That log line
is the early-warning system for the whole feature.

---

## 7. State management (the fetch job)

State lives in **one place**: `progress.json`, owned by `progress.py`. No module keeps
its own idea of what's done.

- The job is a **state machine**, not a loop with flags:
  `IDLE → AUTHENTICATING → ENUMERATING → FETCHING → COMPLETE | FAILED | INTERRUPTED`
- **Commit-then-record, never record-then-commit.** A shortcode is written to
  `progress.json` only after its media is on disk *and* its metadata is captured. Getting
  this backwards means a crash silently skips a post forever (KE-004).
- `progress.json` is written atomically: temp file + `os.replace`. A crash mid-write must
  never corrupt it.
- On startup, `progress.json` is the resume plan. **Never re-download a completed
  shortcode.**
- `capture_stats.incomplete` starts `true` and is set `false` only on clean completion.

---

## 8. Viewer standards

**Plain HTML/CSS/JS. No framework, no build step, no bundler.** This is deliberate
(D-003): the archive must still open in a browser in ten years, with the app long gone.
Do not introduce React, do not introduce a compile step.

- **One fetch, at startup:** load `profile.json`, hold it in a single `ARCHIVE` object.
  Everything renders from that. No other data source exists.
- **Zero network requests after load.** If you add a `fetch()` to a CDN, an analytics
  script, or a Google Font that isn't bundled, you've broken the offline guarantee.
  Fonts are bundled locally or the archive isn't portable.
- Rendering is **pure functions of state**: `render(tab, ARCHIVE)`. No hidden DOM state,
  no jQuery-style mutation-from-anywhere.
- **Uniform media handling** (KE-019): a single image is a carousel of length 1. Never
  branch on `type == "image"` to pick a different rendering path.
- **Graceful degradation is the house style.** Missing audio → song name, no play
  control. Comments not captured → say so, explicitly. Never render a broken player, a
  dead thumbnail, or an empty state that implies data that was never fetched.
- **Provenance is always visible.** The archive banner (captured-at, source URL, what was
  captured) and the per-post provenance strip (shortcode, original URL) are not
  decoration — they're what makes this an *archive* rather than a pile of images. Don't
  remove them for visual cleanliness.
- Accessibility floor, non-negotiable: keyboard navigation through the grid and modal,
  visible focus rings, `Escape` closes the modal, `prefers-reduced-motion` respected,
  alt text from the caption.

---

## 9. Testing

- **No test hits the live Instagram API.** Ever. Fixtures only — checked-in raw response
  samples under `tests/fixtures/raw/`. Live tests are flaky, get you rate-limited, and
  will eventually get the burner banned by CI.
- Every entry in `known-errors.md` that can be tested, is. When you hit a *new* gotcha:
  write the failing test, fix it, **then add it to `known-errors.md`.** All three steps.
- `pytest -m contract` covers every state combination in §2. This is the suite that stops
  the fetcher and viewer from drifting apart.
- Quality regression test: download a fixture, assert the output is **byte-identical** to
  the expected file. This is what catches an accidental Pillow import before it ships.

---

## 10. Scope guard

Before adding a feature, check it against `CLAUDE.md` §1 non-goals and `decisions.md`.

Specifically, these are **out of scope and stay out**: any hosted/multi-tenant mode; any
sharing, publishing, or re-hosting of downloaded content; any image "enhancement" or
upscaling; any password-based auth. These aren't backlog items — they're boundaries. A
proposal to add one is a proposal to build a different product.
