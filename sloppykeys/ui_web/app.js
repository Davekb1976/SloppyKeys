// SloppyKeys — UI controller
// Full-page screen switching, settings categories, window controls.

(function () {
  "use strict";

  // ---- Screen navigation ----
  const navButtons = document.querySelectorAll(".nav-btn[data-screen]");
  const screens = document.querySelectorAll(".screen");

  function switchScreen(name) {
    screens.forEach((s) => s.classList.toggle("active", s.id === "screen-" + name));
    navButtons.forEach((b) => b.classList.toggle("active", b.dataset.screen === name));
    // When wired to pywebview: show/hide the Roblox HWND based on whether
    // the dashboard is active (the only screen that needs the game visible).
    if (window.pywebview && pywebview.api && pywebview.api.set_game_visible) {
      pywebview.api.set_game_visible(name === "dashboard");
    }
  }

  navButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchScreen(btn.dataset.screen));
  });

  // ---- Settings category navigation ----
  const catButtons = document.querySelectorAll(".settings-nav-btn[data-cat]");
  const categories = document.querySelectorAll(".settings-category[data-cat]");

  function switchCategory(cat) {
    categories.forEach((el) => el.classList.toggle("active", el.dataset.cat === cat));
    catButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.cat === cat));
  }

  catButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchCategory(btn.dataset.cat));
  });

  // ---- Window dragging ----
  // One call on mousedown; the backend then tracks the cursor itself until the
  // button comes up. Sending a delta per mousemove instead put a bridge round
  // trip on every frame, which is what made the drag stutter.
  const dragEl = document.getElementById("drag-handle");
  if (dragEl) {
    dragEl.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      if (window.pywebview && pywebview.api) pywebview.api.begin_drag();
    });
  }

  // ---- Window controls ----
  document.getElementById("btn-minimize").addEventListener("click", () => {
    if (window.pywebview && pywebview.api) pywebview.api.minimize_window();
  });
  document.getElementById("btn-close").addEventListener("click", () => {
    if (window.pywebview && pywebview.api) pywebview.api.close_window();
  });

  // ---- Log ----
  const logList = document.getElementById("log-list");
  const LOG_MAX = 500;

  window.addLog = function (line) {
    const div = document.createElement("div");
    div.className = "log-line";
    div.textContent = "> " + line;
    logList.appendChild(div);
    while (logList.childElementCount > LOG_MAX) logList.removeChild(logList.firstElementChild);
    logList.scrollTop = logList.scrollHeight;
  };

  document.getElementById("btn-clear-log").addEventListener("click", () => {
    logList.innerHTML = "";
  });

  // ---- Macro controls ----
  const btnStart = document.getElementById("btn-start");
  const btnStop = document.getElementById("btn-stop");
  const statAction = document.getElementById("stat-action");
  const statGamemode = document.getElementById("stat-gamemode");
  const statCycle = document.getElementById("stat-cycle");

  // ---- Gamemode selector ----
  const selGamemode = document.getElementById("sel-gamemode");
  const selMap = document.getElementById("sel-map");
  const selTarget = document.getElementById("sel-target");

  function fillSelect(el, items, placeholder) {
    el.innerHTML = '<option value="">' + (placeholder || "—") + "</option>";
    items.forEach((item) => {
      const opt = document.createElement("option");
      opt.value = item;
      opt.textContent = item;
      el.appendChild(opt);
    });
  }

  function loadGamemodes() {
    if (!window.pywebview || !pywebview.api) return;
    pywebview.api.get_gamemodes().then((modes) => fillSelect(selGamemode, modes, "—"));
  }

  selGamemode.addEventListener("change", () => {
    selMap.innerHTML = '<option value="">—</option>';
    selTarget.innerHTML = '<option value="">—</option>';
    if (!selGamemode.value || !window.pywebview) return;
    pywebview.api.get_maps(selGamemode.value).then((maps) => fillSelect(selMap, maps, "—"));
  });

  selMap.addEventListener("change", () => {
    selTarget.innerHTML = '<option value="">—</option>';
    if (!selGamemode.value || !selMap.value || !window.pywebview) return;
    pywebview.api.get_targets(selGamemode.value, selMap.value).then((targets) => {
      if (targets.length > 0) fillSelect(selTarget, targets, "—");
    });
  });

  window.addEventListener("pywebviewready", loadGamemodes);

  btnStart.addEventListener("click", () => {
    if (!window.pywebview || !pywebview.api) return;
    const gm = selGamemode.value;
    const map = selMap.value;
    const tgt = selTarget.value;
    // Ask the backend for the config path, then start.
    pywebview.api.get_config_path(gm, map, tgt).then((path) => {
      pywebview.api.start_macro(gm, map, tgt, path).then((r) => {
        if (!r.ok) window.addLog("Start blocked: " + r.error);
      });
    });
  });

  btnStop.addEventListener("click", () => {
    if (!window.pywebview || !pywebview.api) return;
    pywebview.api.stop_macro();
  });

  // Called from Python when macro state changes.
  window.onMacroStatus = function (running, cycle, target, phase) {
    btnStart.disabled = running;
    btnStop.disabled = !running;
    statAction.textContent = running ? phase : "Idle";
    statGamemode.textContent = target || "—";
    statCycle.textContent = String(cycle);
  };

  // ---- Game slot geometry ----
  // The backend cuts a hole in the window over this rect, so the rect has to
  // come from where the slot actually rendered rather than a duplicated
  // constant that can drift out of step with the stylesheet.
  const slotEl = document.getElementById("game-slot");

  function reportSlot() {
    if (!slotEl || !window.pywebview || !pywebview.api) return;
    const r = slotEl.getBoundingClientRect();
    pywebview.api.report_slot(r.left, r.top, r.width, r.height);
  }

  window.addEventListener("pywebviewready", reportSlot);
  window.addEventListener("resize", reportSlot);

  // ---- Session clock ----
  const clockEl = document.getElementById("session-clock");
  const startTime = Date.now();

  function tickClock() {
    const s = Math.floor((Date.now() - startTime) / 1000);
    const h = String(Math.floor(s / 3600)).padStart(2, "0");
    const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
    const sec = String(s % 60).padStart(2, "0");
    clockEl.textContent = h + ":" + m + ":" + sec;
  }
  setInterval(tickClock, 1000);
  tickClock();
})();
