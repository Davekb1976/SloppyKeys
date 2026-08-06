/* ============================================================
   SloppyKeys release site — interactions
   Vanilla, no dependencies. Every animated block bails out when
   the visitor asks for reduced motion.
   ============================================================ */
(() => {
  "use strict";

  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  /* ── sticky nav + scroll progress ───────────────────── */
  const nav = $("#nav");
  const bar = $("#scrollProgress");

  const onScroll = () => {
    const y = window.scrollY;
    nav.classList.toggle("stuck", y > 12);

    const max = document.documentElement.scrollHeight - innerHeight;
    bar.style.width = max > 0 ? `${(y / max) * 100}%` : "0%";

    // parallax on the ambient blobs
    if (!reduced) {
      for (const el of blobs) {
        el.style.transform = `translate3d(0, ${y * +el.dataset.parallax * -0.35}px, 0)`;
      }
    }
  };
  const blobs = $$("[data-parallax]");

  let ticking = false;
  addEventListener("scroll", () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { onScroll(); ticking = false; });
  }, { passive: true });
  onScroll();

  /* ── scroll reveal ──────────────────────────────────── */
  const reveals = $$(".reveal");
  for (const el of reveals) {
    if (el.dataset.delay) el.style.setProperty("--d", `${el.dataset.delay}ms`);
  }

  if (reduced || !("IntersectionObserver" in window)) {
    reveals.forEach(el => el.classList.add("in"));
  } else {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.classList.add("in");
        io.unobserve(e.target);
      }
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
    reveals.forEach(el => io.observe(el));
  }

  /* ── cursor spotlight on cards ──────────────────────── */
  if (!reduced && matchMedia("(hover: hover)").matches) {
    for (const card of $$("[data-spotlight]")) {
      card.addEventListener("pointermove", (ev) => {
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx", `${ev.clientX - r.left}px`);
        card.style.setProperty("--my", `${ev.clientY - r.top}px`);
      });
    }
  }

  /* ── count-up stats ─────────────────────────────────── */
  const counters = $$(".count");
  const runCount = (el) => {
    const target = +el.dataset.to;
    if (reduced) { el.textContent = String(target); return; }

    const dur = 900;
    const t0 = performance.now();
    const tick = (now) => {
      const p = Math.min((now - t0) / dur, 1);
      // ease-out cubic
      el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  if ("IntersectionObserver" in window) {
    const cio = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        runCount(e.target);
        cio.unobserve(e.target);
      }
    }, { threshold: 0.6 });
    counters.forEach(el => cio.observe(el));
  } else {
    counters.forEach(runCount);
  }

  /* ── timeline fill tracks the steps list ────────────── */
  const steps = $(".steps");
  const fill = $("#stepsFill");
  if (steps && fill && !reduced) {
    const paint = () => {
      const r = steps.getBoundingClientRect();
      const span = r.height + innerHeight * 0.5;
      const progress = (innerHeight * 0.75 - r.top) / span;
      fill.style.height = `${Math.min(Math.max(progress, 0), 1) * 100}%`;
    };
    addEventListener("scroll", paint, { passive: true });
    addEventListener("resize", paint);
    paint();
  } else if (fill) {
    fill.style.height = "100%";
  }

  /* ── mock session timer ─────────────────────────────── */
  const timer = $("#mockTimer");
  if (timer) {
    let secs = 0;
    const pad = (n) => String(n).padStart(2, "0");
    const tickTimer = () => {
      secs += 1;
      timer.textContent =
        `${pad(Math.floor(secs / 3600))}:${pad(Math.floor(secs / 60) % 60)}:${pad(secs % 60)}`;
    };
    // Cosmetic only — start part-way so it looks like a session in progress.
    secs = 754;
    tickTimer();
    if (!reduced) setInterval(tickTimer, 1000);
  }

  /* ── animated process log in the app mock ───────────── */
  const logEl = $("#mockLog");
  const LINES = [
    ["12:04:02", "camera setup complete", "ok"],
    ["12:04:03", "searching play.png", ""],
    ["12:04:05", "play matched 0.98 — click (408, 512)", "ok"],
    ["12:04:07", "gamemode story.png matched", "ok"],
    ["12:04:09", "scanning stage band (0, 428, 814, 24)", ""],
    ["12:04:11", "scroll 3 notches", ""],
    ["12:04:13", "rose_kingdom.png matched 0.96", "ok"],
    ["12:04:14", "act 5 -> client (596, 341)", ""],
    ["12:04:16", "hard mode ON", "ok"],
    ["12:04:17", "confirm -> start", ""],
    ["12:04:22", "joined stage — run active", "ok"],
  ];

  if (logEl) {
    const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
    const render = (n) => {
      // Keep only the last 6 lines visible so the panel never overflows.
      logEl.innerHTML = LINES.slice(Math.max(0, n - 6), n)
        .map(([t, msg, cls]) =>
          `<span class="t">[${t}]</span> <span class="${cls}">${esc(msg)}</span>`)
        .join("\n");
    };

    if (reduced) {
      render(LINES.length);
    } else {
      let i = 0;
      const step = () => {
        i = i >= LINES.length ? 1 : i + 1;
        render(i);
        setTimeout(step, i === LINES.length ? 2600 : 900);
      };
      step();
    }
  }

  /* ── copy-to-clipboard ──────────────────────────────── */
  for (const btn of $$(".copy")) {
    btn.addEventListener("click", async () => {
      const src = $(btn.dataset.copy);
      if (!src) return;
      try {
        await navigator.clipboard.writeText(src.textContent.trim());
        const was = btn.textContent;
        btn.textContent = "Copied";
        btn.classList.add("done");
        setTimeout(() => { btn.textContent = was; btn.classList.remove("done"); }, 1600);
      } catch (err) {
        btn.textContent = "Press Ctrl+C";
        // Fall back to selecting the text so the visitor can copy manually.
        const range = document.createRange();
        range.selectNodeContents(src);
        const sel = getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
    });
  }

  /* ── latest release ─────────────────────────────────────
     Every version on the page is markup with a fallback already in it, so the page is
     correct-ish with JS off and exact with it on. `data-sk-version` holds a template
     ("v{v}" or "{v}"); `[data-sk-setup]` gets pointed straight at the installer asset.

     The static fallbacks are only bumped when the site is next touched — that is the
     point of fetching: nobody has to remember.                    */
  const REPO = "Davekb1976/SloppyKeys";

  async function showLatestRelease() {
    let release;
    try {
      const response = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
        headers: { Accept: "application/vnd.github+json" },
      });
      if (!response.ok) return;  // no releases yet, or rate-limited: keep the fallbacks
      release = await response.json();
    } catch (err) {
      return;  // offline. The markup already says something sensible.
    }

    const version = String(release.tag_name || "").replace(/^v/, "");
    if (!/^\d+\.\d+\.\d+$/.test(version)) return;
    for (const node of $$("[data-sk-version]")) {
      node.textContent = node.dataset.skVersion.replace("{v}", version);
    }

    const setup = (release.assets || []).find(
      (asset) => asset.name === `SloppyKeys-Setup-${version}.exe`
    );
    if (!setup) return;
    for (const link of $$("[data-sk-setup]")) {
      link.href = setup.browser_download_url;
    }
  }

  showLatestRelease();
})();
