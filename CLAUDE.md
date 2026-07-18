# CLAUDE.md

Root guidance for this workspace. Read this before touching any file.

---

## 1. Project overview

**Name:** `igarchive` (working title)

**One line:** A local, single-launch desktop tool that downloads a public Instagram
profile in full and lets you browse it offline as if it were still online.

**The gap it fills:** Existing bulk downloaders (wfdownloader, etc.) save *media files*
and nothing else. They discard captions, comments, highlights, and music metadata,
and they dump everything into a flat folder with no way to navigate it. `igarchive`
captures the **metadata alongside the media** and ships a viewer that reconstructs
the profile — grid, carousels, reels, highlights, comments, song attribution.

**Non-goals — do not build these:**
- A hosted/multi-tenant web service. This is a **local-only** tool.
- Any redistribution, re-hosting, or public sharing of downloaded content.
- Any feature that re-encodes, upscales, or "enhances" downloaded media.
- Password entry or password storage of any kind. See §5.

---

## 2. Architecture map

```
                      ┌──────────────────────────┐
                      │  launcher.py (FastAPI)   │  double-click entry point
                      │  serves UI on localhost  │  opens browser automatically
                      └────────────┬─────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
      ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
      │  session.py  │     │  fetcher.py  │     │ progress.py  │
      │ cookie-jar   │────▶│ Instaloader  │◀───▶│ resumable    │
      │ import only  │     │ AS A LIBRARY │     │ state        │
      └──────────────┘     └──────┬───────┘     └──────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
             ┌───────────┐ ┌───────────┐ ┌────────────┐
             │ media.py  │ │ music.py  │ │normalizer  │
             │ byte-for- │ │ FRAGILE   │ │    .py     │
             │ byte dl + │ │ raw dict  │ │ builds the │
             │ ffmpeg -c │ │ access    │ │ contract   │
             │   copy    │ │ ISOLATED  │ │            │
             └───────────┘ └───────────┘ └─────┬──────┘
                                               │
                                               ▼
                                    archives/<username>/
                                      profile.json   ◀── THE CONTRACT
                                      progress.json
                                      media/
                                               │
                                               ▼
                                      ┌────────────────┐
                                      │ viewer/ (HTML) │
                                      │ reads          │
                                      │ profile.json   │
                                      │ ONLY           │
                                      └────────────────┘
```

**The single most important rule in this codebase:** `profile.json` is the contract
between the fetcher half and the viewer half. The viewer never calls Instagram, never
imports Python, and never knows Instaloader exists. It reads `profile.json` and local
files under `media/`. If you are tempted to have the viewer reach back into the
fetcher, stop — you are breaking the design.

### Module responsibilities

| Module | Owns | Must NOT |
|---|---|---|
| `launcher.py` | FastAPI app, static file serving, browser auto-open, job orchestration | Contain scraping logic |
| `session.py` | Importing an existing browser cookie jar; validating it | Ever accept, prompt for, or store a password |
| `fetcher.py` | Instaloader **library** calls, pagination, rate limiting, backoff | Shell out to the Instaloader CLI |
| `media.py` | Streaming bytes to disk; ffmpeg audio extraction | Open, decode, or re-save any image or video |
| `music.py` | Reaching into raw post metadata for song info | Leak raw-dict access into any other module |
| `progress.py` | `progress.json`; what's done, what's pending | Hold media in memory |
| `normalizer.py` | Emitting `profile.json` against `schema.py` | Make network calls |
| `schema.py` | Pydantic models; the single source of truth for the contract | Contain business logic |
| `viewer/` | Rendering the archive | Touch the network, or any file outside its archive dir |

---

## 3. Development environment assumptions

- **Python 3.11+**
- **Instaloader** — used **as a library**, never as a subprocess. Shelling out to the
  CLI throws away the raw metadata dict, which is the only place song info lives.
- **FastAPI + Uvicorn** — local server, bound to `127.0.0.1` only. Never `0.0.0.0`.
- **httpx** — media downloads, streaming.
- **Pydantic v2** — schema enforcement on `profile.json`.
- **ffmpeg** — bundled binary, invoked **only** with `-c copy`.
- **PyInstaller** — packaging to a single double-clickable artifact.
- No Node, no Electron, no build step for the viewer. The viewer is hand-written
  HTML/CSS/JS served as static files. Keep it that way — it's what makes the archive
  portable and future-proof.

**Platform target:** desktop (Windows/macOS/Linux). Single user. No auth, no accounts,
no telemetry.

---

## 4. Build / run commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Run in dev (hot reload, no packaging)
python -m igarchive.launcher --dev

# Run the viewer against an existing archive without any network
python -m igarchive.launcher --serve-only archives/<username>

# Tests
pytest                      # unit
pytest -m contract          # schema/contract tests — MUST pass before any commit
ruff check . && ruff format --check .
mypy src/

# Package the double-click artifact
python build.py             # wraps PyInstaller; bundles ffmpeg + viewer/
```

**Rules for commands:**
- Never add a build step to the viewer. No bundler, no transpiler.
- `pytest -m contract` is the gate. If `profile.json` changes shape, that suite fails
  first, on purpose.
- Do not add commands that hit the live Instagram API in tests. Fixtures only. See
  `memory/known-errors.md`.

---

## 5. Hard constraints (violating these is a bug, not a preference)

1. **Local only.** The server binds to `127.0.0.1`. There is no deploy target.
2. **No password handling.** Authentication happens by importing a cookie jar from a
   browser the user already logged into. The app never sees, prompts for, or stores a
   password. If a session dies, the app says so and offers re-import — it does not ask
   for credentials.
3. **Burner account, always.** Docs and UI must state that the session should come from
   a throwaway account, never the user's real one. Scraping gets accounts banned; that
   is the expected end-state of the burner and it must never be the user's main.
4. **Never re-encode.** Media is streamed to disk byte-for-byte. ffmpeg runs with
   `-c copy` only. Opening a JPEG and writing it back out is a silent quality bug.
5. **Always rate limit.** Randomized sleeps, exponential backoff on 429, a hard
   per-session request ceiling. Every network path must be resumable.
6. **Personal archives only.** The tool exists to make local, personal copies. It must
   not grow features that publish, share, or redistribute what it downloads.

---

## 6. Where to look next

- `docs/project-overview.md` — personas, features, success metrics
- `memory/decisions.md` — why the architecture is the way it is. **Read before
  proposing changes.** Most "obvious improvements" were already considered and rejected
  for reasons recorded there.
- `memory/known-errors.md` — the traps. Read before debugging anything.
- `skills/guidelines.md` — coding standards, component and state conventions.
