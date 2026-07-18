/* igarchive viewer — reads profile.json and local media/ files. Nothing else.
   One fetch at startup; zero network requests after load (D-003).
   Hand-built to match Instagram's dark web UI. No framework, on purpose. */
"use strict";

let ARCHIVE = null;
let TAB = "posts";

const app = document.getElementById("app");
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtNum = n => n == null ? "" : Intl.NumberFormat().format(n);
const fmtCompact = n => n == null ? "" :
  Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
const altFor = post => (post.caption || `Post ${post.shortcode}`).split("\n")[0].slice(0, 120);

// Instagram-style ages: 3d, 1w, 199w
function fmtAge(iso) {
  if (!iso) return "";
  const days = Math.max(0, (Date.now() - new Date(iso)) / 864e5);
  if (days < 1) return `${Math.max(1, Math.floor(days * 24))}h`;
  if (days < 7) return `${Math.floor(days)}d`;
  return `${Math.floor(days / 7)}w`;
}
const fmtDate = iso => iso ? new Date(iso).toLocaleDateString(undefined,
  { year: "numeric", month: "long", day: "numeric" }) : "";

const I = {
  carousel: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H9a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zM5 7H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-1H5z"/></svg>`,
  reel: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M17 2H7a5 5 0 0 0-5 5v10a5 5 0 0 0 5 5h10a5 5 0 0 0 5-5V7a5 5 0 0 0-5-5zM9.6 4h4.06l1.66 3H11.2zM4.1 6.3A3 3 0 0 1 7 4h.3l1.6 3H4zm15.8.7h-3.9l-1.6-3H17a3 3 0 0 1 2.9 3zM10 16.9V10l6 3.4z"/></svg>`,
  heart: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 21S3.5 15.4 3.5 9.6C3.5 6.6 5.7 4.5 8.3 4.5c1.6 0 3 .8 3.7 2 .7-1.2 2.1-2 3.7-2 2.6 0 4.8 2.1 4.8 5.1C20.5 15.4 12 21 12 21z"/></svg>`,
  heartFill: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 21S3.5 15.4 3.5 9.6C3.5 6.6 5.7 4.5 8.3 4.5c1.6 0 3 .8 3.7 2 .7-1.2 2.1-2 3.7-2 2.6 0 4.8 2.1 4.8 5.1C20.5 15.4 12 21 12 21z"/></svg>`,
  comment: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3a9 9 0 0 1 9 9 9 9 0 0 1-9 9 9.2 9.2 0 0 1-4-.9L3 21l.9-5A9 9 0 0 1 12 3z"/></svg>`,
  share: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 3 3 10.5l7 3.5L14 21z M21 3 10 14"/></svg>`,
  save: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M19 21l-7-5-7 5V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1z"/></svg>`,
  eye: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z"/><circle cx="12" cy="12" r="2.8" fill="currentColor" stroke="none"/></svg>`,
  note: `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M9 3v10.6a3.5 3.5 0 1 0 2 3.2V7h7v6.6a3.5 3.5 0 1 0 2 3.2V3z"/></svg>`,
};

// Cache-bust: archives get updated in place (resumes, backfills) and a stale
// cached profile.json makes the viewer show yesterday's archive.
fetch(`profile.json?t=${Date.now()}`)
  .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); })
  .then(data => { ARCHIVE = data; app.removeAttribute("aria-busy"); render(); })
  .catch(e => { app.textContent = `Could not load profile.json — ${e.message}`; });

function render() {
  const a = ARCHIVE, p = a.profile, s = a.capture_stats, o = a.capture_options;
  const gaps = [];
  if (s.incomplete) gaps.push("interrupted run — incomplete");
  if (!o.comments) gaps.push("comments not captured");
  if (!o.highlights) gaps.push("highlights not captured");
  if (s.audio_files_missing) gaps.push(`${s.audio_files_missing} song file(s) unavailable`);

  app.innerHTML = `
    <div class="banner">
      Archive of <a href="${esc(a.source_url)}">${esc(a.source_url)}</a>,
      captured ${esc(fmtDate(a.captured_at))} ·
      ${s.posts_captured} posts · ${s.highlights_captured} highlights ·
      ${s.comments_captured} comments
      ${gaps.length ? ` · <span class="gap">${esc(gaps.join(" · "))}</span>` : ""}
    </div>
    <header class="profile">
      <img src="${esc(p.avatar.local_path || "")}" alt="Avatar of ${esc(p.username)}">
      <div class="info">
        <h1>${esc(p.username)}${p.is_verified ? " ✔" : ""}</h1>
        <span class="actions" aria-hidden="true">
          <span class="btn primary">Follow</span><span class="btn">Message</span>
        </span>
        <div class="counts">
          <span><b>${fmtNum(p.posts_count)}</b> posts</span>
          <span><b>${fmtNum(p.followers)}</b> followers</span>
          <span><b>${fmtNum(p.following)}</b> following</span>
        </div>
        <div class="fullname">${esc(p.full_name)}</div>
        <div class="bio">${esc(p.biography)}</div>
        ${p.external_url ? `<a class="ext" href="${esc(p.external_url)}">${esc(p.external_url.replace(/^https?:\/\//, ""))}</a>` : ""}
      </div>
    </header>
    <section id="rings-area"></section>
    <nav class="tabs" role="tablist">
      <button role="tab" aria-selected="${TAB === "posts"}" data-tab="posts" aria-label="Posts">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 3h18v18H3zM3 9.5h18M3 14.5h18M9.5 3v18M14.5 3v18"/></svg>
      </button>
      <button role="tab" aria-selected="${TAB === "reels"}" data-tab="reels" aria-label="Reels">
        ${I.reel}
      </button>
    </nav>
    <section id="tab-body"></section>`;

  app.querySelectorAll(".tabs button").forEach(b =>
    b.addEventListener("click", () => { TAB = b.dataset.tab; render(); }));
  document.querySelectorAll(".rail [data-nav]").forEach(b => {
    b.setAttribute("aria-current", String(b.dataset.nav === TAB));
    b.onclick = () => { TAB = b.dataset.nav; render(); window.scrollTo(0, 0); };
  });

  renderHighlights(document.getElementById("rings-area"));
  renderGrid(document.getElementById("tab-body"), TAB === "reels"
    ? ARCHIVE.posts.filter(x => x.type === "reel") : ARCHIVE.posts);
}

function renderGrid(el, posts) {
  if (!posts.length) { el.innerHTML = `<p class="not-captured">Nothing here.</p>`; return; }
  el.innerHTML = `<div class="grid">${posts.map((post, i) => {
    const m = post.media[0];  // a single image is a carousel of length 1 (KE-019)
    if (!m) return "";
    // Videos: prefer the creator-chosen cover; first frame only as a fallback.
    const tile = m.kind === "video"
      ? (m.thumbnail_local_path
          ? `<img src="${esc(m.thumbnail_local_path)}" alt="" loading="lazy">`
          : `<video src="${esc(m.local_path)}" preload="metadata" muted></video>`)
      : `<img src="${esc(m.local_path)}" alt="" loading="lazy">`;
    // Reels tab: every tile is a reel — no badge, like the real page.
    const badge = post.type === "carousel" ? I.carousel
      : post.type === "reel" && TAB !== "reels" ? I.reel : "";
    const views = TAB === "reels" && post.views != null
      ? `<span class="views">${I.eye} ${fmtCompact(post.views)}</span>` : "";
    const hover = `<span class="hover">
        <span>${I.heartFill} ${fmtCompact(post.likes)}</span>
        ${post.comments_captured ? `<span>${I.comment} ${fmtCompact(post.comments.length)}</span>` : ""}
      </span>`;
    return `<button class="tile" data-i="${i}" aria-label="${esc(altFor(post))}">
      ${tile}${badge ? `<span class="badge">${badge}</span>` : ""}${views}${hover}</button>`;
  }).join("")}</div>`;
  el.querySelectorAll(".tile").forEach(t =>
    t.addEventListener("click", () => openModal(posts[+t.dataset.i])));
}

function songLabel(music) {
  // KE-010/KE-011: music null = no bar; title/artist may be absent (original audio).
  if (!music) return "";
  return [music.title, music.artist].filter(Boolean).join(" · ");
}

const avatarPh = name =>
  `<span class="avatar-ph" aria-hidden="true">${esc((name || "?")[0].toUpperCase())}</span>`;

/* ---------------- post modal ---------------- */
const modal = document.getElementById("modal");
let modalPost = null, mediaIndex = 0, lastFocus = null;

function openModal(post) {
  modalPost = post; mediaIndex = 0; lastFocus = document.activeElement;
  modal.hidden = false;
  renderModal();
  modal.querySelector(".close").focus();
}

function renderModal() {
  const post = modalPost, many = post.media.length > 1;
  // Stitched carousel: items laid edge-to-edge in a scroll-snap strip, so
  // multi-part panoramas line up and swiping scrolls smoothly.
  modal.querySelector(".media-slot").innerHTML = `<div class="strip">${post.media.map((m, i) =>
    m.kind === "video"
      ? `<video src="${esc(m.local_path)}" controls loop ${!many && i === 0 ? "autoplay" : ""}
           ${m.thumbnail_local_path ? `poster="${esc(m.thumbnail_local_path)}"` : ""}></video>`
      : `<img src="${esc(m.local_path)}" alt="${esc(altFor(post))} (${i + 1}/${post.media.length})">`
  ).join("")}</div>`;
  const strip = modal.querySelector(".strip");
  strip.addEventListener("scroll", () => requestAnimationFrame(() => {
    const kids = [...strip.children];
    const center = strip.scrollLeft + strip.clientWidth / 2;
    const nearest = kids.reduce((best, el, i) =>
      Math.abs(el.offsetLeft + el.offsetWidth / 2 - center) <
      Math.abs(kids[best].offsetLeft + kids[best].offsetWidth / 2 - center) ? i : best, 0);
    if (nearest !== mediaIndex) { mediaIndex = nearest; syncCarouselUI(); }
  }), { passive: true });
  syncCarouselUI();
  renderMeta();
}

function syncCarouselUI() {
  const post = modalPost, many = post.media.length > 1;
  modal.querySelector(".prev").hidden = !many || mediaIndex === 0;
  modal.querySelector(".next").hidden = !many || mediaIndex === post.media.length - 1;
  modal.querySelector(".dots").innerHTML = many
    ? post.media.map((_, i) => `<i class="${i === mediaIndex ? "on" : ""}"></i>`).join("") : "";
}

function scrollCarousel(dir) {
  const strip = modal.querySelector(".strip");
  if (!strip) return;
  mediaIndex = Math.min(Math.max(mediaIndex + dir, 0), modalPost.media.length - 1);
  const el = strip.children[mediaIndex];
  strip.scrollTo({ left: el.offsetLeft + el.offsetWidth / 2 - strip.clientWidth / 2 });
  syncCarouselUI();
}

function renderMeta() {
  const post = modalPost;
  const user = ARCHIVE.profile.username;
  const avatar = ARCHIVE.profile.avatar.local_path;
  // Caption rendered as the first comment, like the real modal.
  const captionRow = post.caption ? `
    <div class="comment">
      <img class="avatar-s" src="${esc(avatar || "")}" alt="">
      <div class="body"><span class="who">${esc(user)}</span><span class="text">${esc(post.caption)}</span>
        <div class="meta">${esc(fmtAge(post.taken_at))}</div></div>
    </div>` : "";

  const comments = post.comments_captured
    ? (post.comments.length
        ? post.comments.map(renderComment).join("")
        : (post.caption ? "" : `<p class="not-captured">No comments</p>`))
    : `<p class="not-captured">Comments were not captured in this snapshot</p>`;

  const music = post.music;
  // Three states (KE-010): no music → no bar; music, no file → bar without player;
  // music with file → bar with play toggle. Never a broken player.
  const songbar = music && songLabel(music) ? `
    <div class="songbar">${I.note}<span class="t">${esc(songLabel(music))}</span>
      ${music.audio_local_path ? `
        <button class="songplay" aria-label="Play song">▶</button>
        <audio src="${esc(music.audio_local_path)}"></audio>` : ""}
    </div>` : "";

  modal.querySelector(".meta-pane").innerHTML = `
    <div class="mp-head">
      <img class="avatar-s" src="${esc(avatar || "")}" alt="">${esc(user)}
    </div>
    <div class="mp-scroll">${captionRow}${comments}</div>
    <div class="mp-foot">
      ${songbar}
      <div class="actrow" aria-hidden="true">${I.heart}${I.comment}${I.share}<span class="save">${I.save}</span></div>
      <div class="likes">${fmtNum(post.likes)} likes${post.views != null ? ` · ${fmtCompact(post.views)} views` : ""}</div>
      <div class="when">${esc(fmtDate(post.taken_at))}</div>
      <div class="provenance">${esc(post.shortcode)} · <a href="${esc(post.source_url)}">${esc(post.source_url)}</a></div>
    </div>`;

  const audio = modal.querySelector(".songbar audio");
  if (audio) {
    const btn = modal.querySelector(".songplay");
    const sync = () => { btn.textContent = audio.paused ? "▶" : "❚❚"; };
    btn.addEventListener("click", () => audio.paused ? audio.play() : audio.pause());
    audio.addEventListener("play", sync);
    audio.addEventListener("pause", sync);
    const isPhoto = !post.media.some(m => m.kind === "video");
    // Instagram plays the creator-chosen segment of the track, looped. Photo posts
    // carry the full song file, so seek+loop the snippet; a reel's m4a already IS
    // the used segment. Unknown timing → loop the whole track.
    const seg = isPhoto && music.snippet_start_ms != null ? {
      start: music.snippet_start_ms / 1000,
      end: music.snippet_duration_ms != null
        ? (music.snippet_start_ms + music.snippet_duration_ms) / 1000 : null,
    } : null;
    audio.loop = !seg;
    if (seg) {
      const toStart = () => { audio.currentTime = seg.start; };
      audio.addEventListener("loadedmetadata", toStart);
      audio.addEventListener("ended", () => { toStart(); audio.play().catch(() => {}); });
      audio.addEventListener("timeupdate", () => {
        if (seg.end !== null && audio.currentTime >= seg.end) toStart();
      });
    }
    // Autoplay like Instagram — but only on photo posts; a reel's own soundtrack
    // already plays, and doubling it echoes. The tile click counts as the gesture.
    if (isPhoto) audio.play().catch(() => {});
  }
}

function renderComment(c) {
  return `<div class="comment">
    ${avatarPh(c.username)}
    <div class="body"><span class="who">${esc(c.username)}</span><span class="text">${esc(c.text)}</span>
      <div class="meta">${esc(fmtAge(c.created_at))}${c.likes ? ` · ${fmtNum(c.likes)} likes` : ""}</div>
      ${c.replies?.length ? `<div class="replies">${c.replies.map(renderComment).join("")}</div>` : ""}
    </div>
  </div>`;
}

function closeModal() {
  modal.hidden = true;
  modal.querySelector(".media-slot").innerHTML = "";  // stops video playback
  modal.querySelector(".meta-pane").innerHTML = "";   // stops the song too
  if (lastFocus) lastFocus.focus();
}
modal.querySelector(".close").addEventListener("click", closeModal);
modal.querySelector(".prev").addEventListener("click", () => scrollCarousel(-1));
modal.querySelector(".next").addEventListener("click", () => scrollCarousel(1));
modal.addEventListener("click", e => { if (e.target === modal) closeModal(); });

/* ---------------- highlights ---------------- */
const story = document.getElementById("story");
const storyPauseBtn = story.querySelector(".story-pause");
let storyHl = null, storyIndex = 0, storyTimer = null, storyPaused = false;
const autoAdvance = matchMedia("(prefers-reduced-motion: no-preference)").matches;

function setStoryPaused(paused) {
  storyPaused = paused;
  storyPauseBtn.textContent = paused ? "▶" : "❚❚";
  storyPauseBtn.setAttribute("aria-label", paused ? "Resume story" : "Pause story");
  const video = story.querySelector("video");
  if (paused) {
    clearTimeout(storyTimer);
    if (video) video.pause();
  } else if (video) {
    video.play().catch(() => {});
  } else if (autoAdvance) {
    storyTimer = setTimeout(() => stepStory(1), 5000);
  }
}
storyPauseBtn.addEventListener("click", () => setStoryPaused(!storyPaused));

function renderHighlights(el) {
  const hls = ARCHIVE.highlights;
  if (!ARCHIVE.capture_options.highlights)
    { el.innerHTML = `<p class="not-captured">Highlights were not captured in this snapshot</p>`; return; }
  if (!hls.length) { el.innerHTML = ""; return; }  // like the real page: no row at all
  el.innerHTML = `<div class="rings-wrap">
    <button class="nav ring-nav prev" aria-label="Scroll highlights left">‹</button>
    <div class="rings">${hls.map((h, i) => `
      <button class="ring" data-i="${i}" aria-label="Highlight ${esc(h.title)}">
        <span class="rim"><img src="${esc(h.cover.local_path || "")}" alt=""></span>
        <span>${esc(h.title)}</span>
      </button>`).join("")}</div>
    <button class="nav ring-nav next" aria-label="Scroll highlights right">›</button>
  </div>`;
  el.querySelectorAll(".ring").forEach(b =>
    b.addEventListener("click", () => openStory(hls[+b.dataset.i])));
  const row = el.querySelector(".rings");
  const prev = el.querySelector(".ring-nav.prev"), next = el.querySelector(".ring-nav.next");
  const update = () => {
    prev.hidden = row.scrollLeft <= 0;
    next.hidden = row.scrollLeft + row.clientWidth >= row.scrollWidth - 1;
  };
  prev.addEventListener("click", () => row.scrollBy({ left: -row.clientWidth * .8 }));
  next.addEventListener("click", () => row.scrollBy({ left: row.clientWidth * .8 }));
  row.addEventListener("scroll", () => requestAnimationFrame(update), { passive: true });
  update();
}

function openStory(hl) {
  if (!hl.items.length) return;
  // Instagram plays highlight items oldest-first; the capture order is newest-first.
  storyHl = { ...hl, items: [...hl.items].sort((a, b) =>
    (a.taken_at || "") < (b.taken_at || "") ? -1 : 1) };
  storyIndex = 0; lastFocus = document.activeElement;
  story.hidden = false;
  renderStory();
  story.querySelector(".close").focus();
}

function renderStory() {
  clearTimeout(storyTimer);
  storyPaused = false;
  storyPauseBtn.textContent = "❚❚";
  const item = storyHl.items[storyIndex];
  story.querySelector(".story-progress").innerHTML =
    storyHl.items.map((_, i) => `<i class="${i <= storyIndex ? "on" : ""}"></i>`).join("");
  story.querySelector(".story-head").innerHTML = `
    <img class="avatar-s" src="${esc(ARCHIVE.profile.avatar.local_path || "")}" alt="">
    ${esc(storyHl.title)} <span class="age">${esc(fmtAge(item.taken_at))}</span>`;
  const slot = story.querySelector(".story-slot");
  if (item.kind === "video") {
    slot.innerHTML = `<video src="${esc(item.local_path)}" autoplay playsinline></video>`;
    slot.querySelector("video").addEventListener("ended", () => stepStory(1));
  } else {
    slot.innerHTML = `<img src="${esc(item.local_path)}" alt="Highlight item ${storyIndex + 1}">`;
    if (autoAdvance) storyTimer = setTimeout(() => stepStory(1), 5000);
  }
}

function stepStory(dir) {
  const next = storyIndex + dir;
  if (next < 0 || next >= storyHl.items.length) { closeStory(); return; }
  storyIndex = next; renderStory();
}
function closeStory() {
  clearTimeout(storyTimer);
  story.hidden = true;
  story.querySelector(".story-slot").innerHTML = "";
  if (lastFocus) lastFocus.focus();
}
story.querySelector(".close").addEventListener("click", closeStory);
story.querySelector(".prev").addEventListener("click", () => stepStory(-1));
story.querySelector(".next").addEventListener("click", () => stepStory(1));
story.addEventListener("click", e => {
  if (e.target === story || e.target.closest(".story-slot")) stepStory(1);
});

/* ---------------- keyboard ---------------- */
document.addEventListener("keydown", e => {
  if (!story.hidden) {
    if (e.key === "Escape") closeStory();
    if (e.key === "ArrowRight") stepStory(1);
    if (e.key === "ArrowLeft") stepStory(-1);
  } else if (!modal.hidden) {
    if (e.key === "Escape") closeModal();
    if (e.key === "ArrowRight") scrollCarousel(1);
    if (e.key === "ArrowLeft") scrollCarousel(-1);
  }
});
