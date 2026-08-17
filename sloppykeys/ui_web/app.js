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
    // Remove highlight from previous newest line
    const prev = logList.querySelector(".log-line.newest");
    if (prev) prev.classList.remove("newest");
    const div = document.createElement("div");
    div.className = "log-line newest";
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
  const btnPause = document.getElementById("btn-pause");
  const btnStop = document.getElementById("btn-stop");
  const statAction = document.getElementById("stat-action");
  const statGamemode = document.getElementById("stat-gamemode");
  const statCycle = document.getElementById("stat-cycle");
  let macroPaused = false;

  btnStart.addEventListener("click", () => {
    if (!window.pywebview || !pywebview.api) return;
    pywebview.api.start_macro().then((r) => {
      if (!r.ok) window.addLog("Start blocked: " + r.error);
    });
  });

  btnPause.addEventListener("click", () => {
    if (!window.pywebview || !pywebview.api) return;
    pywebview.api.toggle_pause();
  });

  btnStop.addEventListener("click", () => {
    if (!window.pywebview || !pywebview.api) return;
    pywebview.api.stop_macro();
  });

  // Called from Python when macro state changes.
  window.onMacroStatus = function (running, cycle, target, phase) {
    btnStart.disabled = running;
    btnPause.disabled = !running;
    btnStop.disabled = !running;
    macroPaused = phase === "paused";
    // Update pause button label
    btnPause.innerHTML = macroPaused
      ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg> Resume <span class="btn-key">F2</span>'
      : '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="4" width="4" height="16"/><rect x="15" y="4" width="4" height="16"/></svg> Pause <span class="btn-key">F2</span>';
    // Status dot
    const dot = document.getElementById("status-dot");
    dot.className = "status-dot" + (running ? (macroPaused ? " paused" : " running") : " stopped");
    // Status text
    statAction.textContent = running ? (macroPaused ? "Paused" : "Running") : "Idle";
    statGamemode.textContent = target || "—";
    statCycle.textContent = String(cycle);
    // Sync compact strip
    const csAction = document.getElementById("compact-action");
    if (csAction) csAction.textContent = running ? (macroPaused ? "Paused" : target || "Running") : "Idle";
    const csStart = document.getElementById("cs-start");
    const csPause = document.getElementById("cs-pause");
    const csStop = document.getElementById("cs-stop");
    if (csStart) csStart.disabled = running;
    if (csPause) csPause.disabled = !running;
    if (csStop) csStop.disabled = !running;
  };

  // Called from Python after a match result is recorded.
  window.onMatchResult = function (won, wins, losses) {
    document.getElementById("stat-wins").textContent = String(wins);
    document.getElementById("stat-losses").textContent = String(losses);
    const total = wins + losses;
    const rate = total > 0 ? Math.round(wins * 100 / total) + "%" : "—";
    document.getElementById("stat-winrate").textContent = rate;
    document.getElementById("stat-last").textContent = won ? "Win" : "Loss";
  };

  // ---- Game slot geometry ----
  // The backend cuts a hole in the window over this rect, so the rect has to
  // come from where the slot actually rendered rather than a duplicated
  // constant that can drift out of step with the stylesheet.
  const slotEl = document.getElementById("game-slot");

  // ---- Compact mode (F7) ----
  let compactMode = false;
  window.toggleCompact = function () {
    if (!window.pywebview || !pywebview.api) return;
    if (!compactMode) {
      switchScreen("dashboard");
      compactMode = true;
      document.body.classList.add("compact-mode");
      pywebview.api.enter_compact();
    } else {
      compactMode = false;
      document.body.classList.remove("compact-mode");
      pywebview.api.exit_compact();
    }
  };

  // Compact strip buttons
  document.getElementById("cs-start").addEventListener("click", () => {
    if (window.pywebview && pywebview.api) pywebview.api.start_macro();
  });
  document.getElementById("cs-pause").addEventListener("click", () => {
    if (!window.pywebview || !pywebview.api) return;
    pywebview.api.toggle_pause();
  });
  document.getElementById("cs-stop").addEventListener("click", () => {
    if (window.pywebview && pywebview.api) pywebview.api.stop_macro();
  });

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

  // ---- Task Queue ----
  let tasks = [];
  let selectedTaskId = null;

  const taskList = document.getElementById("task-list");
  const taskBuilder = document.getElementById("task-builder");
  const taskBuilderEmpty = document.getElementById("task-builder-empty");
  const queueCount = document.getElementById("queue-count");
  const tbMode = document.getElementById("tb-mode");
  const tbMap = document.getElementById("tb-map");
  const tbStage = document.getElementById("tb-stage");
  const tbDifficulty = document.getElementById("tb-difficulty");
  const tbRepeat = document.getElementById("tb-repeat");
  const tbMacro = document.getElementById("tb-macro");

  function renderTaskList() {
    queueCount.textContent = tasks.length + " task" + (tasks.length !== 1 ? "s" : "");
    if (!tasks.length) {
      taskList.innerHTML = '<div class="empty-state">No tasks yet — add one to get started</div>';
      return;
    }
    taskList.innerHTML = tasks.map((t, i) => {
      const title = [t.mode, t.map, t.stage].filter(Boolean).join(" · ") || "Unconfigured";
      const meta = (t.difficulty || "") + " · ×" + (t.repeat || 1) + (t.macro ? " · " + t.macro : "");
      const sel = t.id === selectedTaskId ? " selected" : "";
      return `<div class="task-card${sel}" data-id="${t.id}">
        <span class="task-card-index">${i + 1}</span>
        <div class="task-card-body">
          <div class="task-card-title">${title}</div>
          <div class="task-card-meta">${meta}</div>
        </div>
      </div>`;
    }).join("");
    taskList.querySelectorAll(".task-card").forEach((card) => {
      card.addEventListener("click", () => selectTask(card.dataset.id));
    });
  }

  function selectTask(id) {
    selectedTaskId = id;
    renderTaskList();
    const task = tasks.find((t) => t.id === id);
    if (!task) { showBuilderEmpty(); return; }
    taskBuilder.style.display = "";
    taskBuilderEmpty.style.display = "none";
    // Populate fields
    tbMode.value = task.mode || "";
    // Toggle Challenge vs Standard fields based on mode
    const isChallenge = tbMode.value === "Challenge";
    document.getElementById("tb-standard-fields").style.display = isChallenge ? "none" : "contents";
    document.getElementById("tb-challenge-fields").style.display = isChallenge ? "block" : "none";
    if (isChallenge) {
      renderChallengeMapGrid();
    } else {
      loadMaps(task.mode, task.map);
      loadStages(task.mode, task.map, task.stage);
      tbDifficulty.value = task.difficulty || "Normal";
      tbRepeat.value = task.repeat || 1;
      tbMacro.value = task.macro || "";
    }
  }

  function showBuilderEmpty() {
    taskBuilder.style.display = "none";
    taskBuilderEmpty.style.display = "";
  }

  async function loadTasks() {
    if (!window.pywebview || !pywebview.api) return;
    tasks = await pywebview.api.get_tasks() || [];
    renderTaskList();
    if (selectedTaskId) selectTask(selectedTaskId);
    else showBuilderEmpty();
  }

  async function loadMaps(mode, selected) {
    if (!window.pywebview || !pywebview.api || !mode) {
      tbMap.innerHTML = '<option value="">—</option>';
      return;
    }
    const maps = await pywebview.api.get_maps(mode);
    tbMap.innerHTML = '<option value="">—</option>' + maps.map((m) => `<option value="${m}"${m === selected ? " selected" : ""}>${m}</option>`).join("");
  }

  async function loadStages(mode, map, selected) {
    if (!window.pywebview || !pywebview.api || !mode || !map) {
      tbStage.innerHTML = '<option value="">—</option>';
      return;
    }
    const stages = await pywebview.api.get_targets(mode, map);
    if (!stages.length) { tbStage.innerHTML = '<option value="">—</option>'; return; }
    tbStage.innerHTML = '<option value="">—</option>' + stages.map((s) => `<option value="${s}"${s === selected ? " selected" : ""}>${s}</option>`).join("");
  }

  function saveCurrentTask() {
    if (!selectedTaskId || !window.pywebview || !pywebview.api) return;
    const changes = {
      mode: tbMode.value,
      map: tbMap.value,
      stage: tbStage.value,
      difficulty: tbDifficulty.value,
      repeat: Math.max(1, parseInt(tbRepeat.value) || 1),
      macro: tbMacro.value,
    };
    // Challenge-specific: per-map macros + slot enables
    if (tbMode.value === "Challenge") {
      const t = tasks.find(x => x.id === selectedTaskId);
      changes.challenge_macros = (t && t.challenge_macros) || {};
      changes.challenge_slots = [
        document.getElementById("tb-chal-slot1")?.classList.contains("on") !== false,
        document.getElementById("tb-chal-slot2")?.classList.contains("on") !== false,
        document.getElementById("tb-chal-slot3")?.classList.contains("on") !== false,
      ];
    }
    pywebview.api.update_task(selectedTaskId, changes).then(() => {
      const t = tasks.find((x) => x.id === selectedTaskId);
      if (t) Object.assign(t, changes);
      renderTaskList();
    });
  }

  // Cascade: mode → maps, map → stages
  tbMode.addEventListener("change", () => {
    const isChallenge = tbMode.value === "Challenge";
    document.getElementById("tb-standard-fields").style.display = isChallenge ? "none" : "contents";
    document.getElementById("tb-challenge-fields").style.display = isChallenge ? "block" : "none";
    if (isChallenge) {
      renderChallengeMapGrid();
    } else {
      loadMaps(tbMode.value, "");
      tbStage.innerHTML = '<option value="">—</option>';
    }
    saveCurrentTask();
  });
  tbMap.addEventListener("change", () => {
    loadStages(tbMode.value, tbMap.value, "");
    saveCurrentTask();
  });
  tbStage.addEventListener("change", saveCurrentTask);
  tbDifficulty.addEventListener("change", saveCurrentTask);
  tbRepeat.addEventListener("change", saveCurrentTask);
  tbMacro.addEventListener("change", saveCurrentTask);

  document.getElementById("btn-add-task").addEventListener("click", () => {
    if (!window.pywebview || !pywebview.api) return;
    const newTask = { mode: "Story", map: "", stage: "", difficulty: "Normal", repeat: 1, macro: "" };
    pywebview.api.add_task(newTask).then((r) => {
      if (r.ok) {
        newTask.id = r.id;
        tasks.push(newTask);
        selectTask(r.id);
        renderTaskList();
      }
    });
  });

  document.getElementById("btn-clear-tasks").addEventListener("click", () => {
    if (!window.pywebview || !pywebview.api) return;
    pywebview.api.clear_tasks().then(() => {
      tasks = [];
      selectedTaskId = null;
      renderTaskList();
      showBuilderEmpty();
    });
  });

  // Task queue presets: save/load/delete
  document.getElementById("btn-save-queue").addEventListener("click", async () => {
    if (!window.pywebview || !pywebview.api) return;
    const nameInput = document.getElementById("queue-preset-name");
    const name = nameInput.value.trim();
    if (!name) { window.addLog("[Queue] Enter a preset name first."); nameInput.focus(); return; }
    const r = await pywebview.api.save_task_preset(name, tasks);
    if (r.ok) { window.addLog("Queue saved: " + name); loadQueuePresets(); }
    else window.addLog("[Queue] Save failed.");
  });

  const queuePresetLoad = document.getElementById("queue-preset-load");
  queuePresetLoad.addEventListener("change", async () => {
    const name = queuePresetLoad.value;
    if (!name || !window.pywebview || !pywebview.api) return;
    const r = await pywebview.api.load_task_preset(name);
    if (r.ok && r.tasks) {
      tasks = r.tasks;
      await pywebview.api.clear_tasks();
      for (const t of tasks) await pywebview.api.add_task(t);
      selectedTaskId = null;
      renderTaskList();
      showBuilderEmpty();
      document.getElementById("queue-preset-name").value = name;
      window.addLog("Queue loaded: " + name);
    }
    queuePresetLoad.value = "";
  });

  document.getElementById("btn-del-queue-preset").addEventListener("click", async () => {
    const nameInput = document.getElementById("queue-preset-name");
    const name = nameInput.value.trim();
    if (!name || !window.pywebview || !pywebview.api) { window.addLog("[Queue] Enter or load a preset name to delete."); return; }
    const r = await pywebview.api.delete_task_preset(name);
    if (r.ok) { window.addLog("Preset deleted: " + name); nameInput.value = ""; loadQueuePresets(); }
    else window.addLog("[Queue] Preset not found.");
  });

  async function loadQueuePresets() {
    if (!window.pywebview || !pywebview.api) return;
    const names = await pywebview.api.list_task_presets();
    queuePresetLoad.innerHTML = '<option value="">Load...</option>' + (names || []).map(n => `<option value="${n}">${n}</option>`).join("");
  }

  document.getElementById("btn-remove-task").addEventListener("click", () => {
    if (!selectedTaskId || !window.pywebview || !pywebview.api) return;
    pywebview.api.remove_task(selectedTaskId).then(() => {
      tasks = tasks.filter((t) => t.id !== selectedTaskId);
      selectedTaskId = null;
      renderTaskList();
      showBuilderEmpty();
    });
  });

  // ---- Challenge per-map macro grid ----
  const CHALLENGE_MAPS = ["School Grounds", "Flower Forest", "Rose Kingdom", "Fairy King Forest", "King's Tomb"];

  function renderChallengeMapGrid() {
    const grid = document.getElementById("tb-challenge-maps");
    if (!grid) return;
    const task = tasks.find(t => t.id === selectedTaskId);
    const mapMacros = (task && task.challenge_macros) || {};
    const slots = (task && task.challenge_slots) || [true, true, true];
    // Update slot toggle states
    ["tb-chal-slot1", "tb-chal-slot2", "tb-chal-slot3"].forEach((id, i) => {
      const btn = document.getElementById(id);
      if (btn) btn.classList.toggle("on", slots[i] !== false);
    });
    grid.innerHTML = CHALLENGE_MAPS.map(m => {
      return `<div class="challenge-map-row">
        <span class="challenge-map-name">${m}</span>
        <select class="setting-select" data-chal-map="${m}" style="height:26px;font-size:11px;">
          <option value="">No Macro</option>
        </select>
      </div>`;
    }).join("");
    // Populate operation options
    if (window.pywebview && pywebview.api) {
      pywebview.api.list_operations().then(names => {
        grid.querySelectorAll("[data-chal-map]").forEach(sel => {
          const mapName = sel.dataset.chalMap;
          const current = mapMacros[mapName] || "";
          sel.innerHTML = '<option value="">No Macro</option>' + names.map(n =>
            `<option value="${n}"${n === current ? " selected" : ""}>${n}</option>`
          ).join("");
          sel.addEventListener("change", () => {
            if (!selectedTaskId) return;
            const t = tasks.find(x => x.id === selectedTaskId);
            if (!t) return;
            if (!t.challenge_macros) t.challenge_macros = {};
            t.challenge_macros[mapName] = sel.value;
            saveCurrentTask();
          });
        });
      });
    }
  }

  // ---- OCR Region Picker (snapshot + draw box) ----
  let ocrRegionKey = null;
  let ocrRegionRect = null;
  let ocrCachedSnapshot = null; // cached Roblox screenshot for Set buttons
  let ocrRegionSpecs = [];       // [{key,label,default}] for onion-skin overlays
  let ocrRegionOverrides = {};   // saved region boxes by key

  async function openRegionPicker(key, dataUri) {
    ocrRegionKey = key;
    ocrRegionRect = null;
    // Refresh the other regions so they show as labeled onion-skin outlines.
    if (window.pywebview && pywebview.api) {
      try {
        ocrRegionSpecs = (await pywebview.api.get_vision_region_specs()) || [];
        ocrRegionOverrides = (await pywebview.api.get_vision_regions()) || {};
      } catch (e) {}
    }
    // Seed with the region's current box so it shows highlighted; redraw to change.
    const savedActive = ocrRegionOverrides[key] || (ocrRegionSpecs.find(s => s.key === key) || {}).default;
    if (savedActive) ocrRegionRect = { x: savedActive[0], y: savedActive[1], w: savedActive[2], h: savedActive[3] };
    document.getElementById("ocr-region-key").textContent = key;
    document.getElementById("ocr-region-readout").textContent = ocrRegionRect
      ? `${ocrRegionRect.x}, ${ocrRegionRect.y}, ${ocrRegionRect.w}×${ocrRegionRect.h}` : "Draw a box";
    document.getElementById("ocr-region-apply").disabled = !ocrRegionRect;
    document.getElementById("ocr-region-modal").style.display = "flex";

    const canvas = document.getElementById("ocr-region-canvas");
    const wrap = document.getElementById("ocr-region-wrap");
    const ctx = canvas.getContext("2d");
    const img = new Image();
    img.onload = () => {
      const wrapW = wrap.clientWidth || 860;
      const wrapH = wrap.clientHeight || 450;
      const scale = Math.min(wrapW / img.naturalWidth, wrapH / img.naturalHeight, 1);
      canvas.width = wrapW;
      canvas.height = wrapH;
      canvas.dataset.scale = scale;
      canvas.dataset.natW = img.naturalWidth;
      canvas.dataset.natH = img.naturalHeight;

      let zoom = 1.0, panX = (wrapW - img.naturalWidth * scale) / 2, panY = (wrapH - img.naturalHeight * scale) / 2;
      let dragging = false, dragStart = null, panning = false, panStart = null;

      function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.translate(panX, panY);
        ctx.scale(zoom, zoom);
        ctx.drawImage(img, 0, 0, img.naturalWidth * scale, img.naturalHeight * scale);
        // Draw a readable label chip (dark pill + bright text) above a box.
        const fontPx = 11 / zoom;
        ctx.font = "600 " + fontPx + "px system-ui";
        ctx.textBaseline = "alphabetic";
        function drawLabel(text, x, y, color) {
          const padX = 4 / zoom, padY = 2 / zoom;
          const tw = ctx.measureText(text).width;
          const th = fontPx;
          let ly = y - 2 / zoom;                 // sit just above the box
          if (ly - th - padY * 2 < 0) ly = y + th + padY * 2 + 2 / zoom; // flip below if clipped at top
          ctx.fillStyle = "rgba(15, 18, 26, 0.85)";
          ctx.fillRect(x, ly - th - padY * 2, tw + padX * 2, th + padY * 2);
          ctx.fillStyle = color;
          ctx.fillText(text, x + padX, ly - padY);
        }
        // Onion-skin: every other saved region, dimmed, with its label.
        ocrRegionSpecs.forEach(s => {
          if (s.key === ocrRegionKey) return; // the one being edited is drawn below
          const box = ocrRegionOverrides[s.key] || s.default;
          if (!box) return;
          const bx = box[0] * scale, by = box[1] * scale, bw = box[2] * scale, bh = box[3] * scale;
          ctx.strokeStyle = "rgba(226, 232, 240, 0.7)";
          ctx.lineWidth = 1 / zoom;
          ctx.strokeRect(bx, by, bw, bh);
          drawLabel(s.label, bx, by, "#e2e8f0");
        });
        if (ocrRegionRect) {
          const label = (ocrRegionSpecs.find(s => s.key === ocrRegionKey) || {}).label || ocrRegionKey;
          const rx = ocrRegionRect.x * scale, ry = ocrRegionRect.y * scale;
          ctx.strokeStyle = "#a78bfa";
          ctx.lineWidth = 2 / zoom;
          ctx.strokeRect(rx, ry, ocrRegionRect.w * scale, ocrRegionRect.h * scale);
          ctx.fillStyle = "rgba(139, 92, 246, 0.15)";
          ctx.fillRect(rx, ry, ocrRegionRect.w * scale, ocrRegionRect.h * scale);
          drawLabel(label, rx, ry, "#c4b5fd");
        }
        ctx.restore();
      }
      draw();

      function screenToImage(sx, sy) {
        return [Math.round((sx - panX) / zoom / scale), Math.round((sy - panY) / zoom / scale)];
      }

      canvas.onwheel = (e) => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        const oldZoom = zoom;
        zoom = Math.max(0.5, Math.min(5, zoom * (e.deltaY < 0 ? 1.15 : 1/1.15)));
        panX = mx - (mx - panX) * (zoom / oldZoom);
        panY = my - (my - panY) * (zoom / oldZoom);
        draw();
      };
      canvas.onmousedown = (e) => {
        if (e.button === 1) { panning = true; panStart = {x: e.clientX - panX, y: e.clientY - panY}; e.preventDefault(); return; }
        if (e.button === 0) {
          const rect = canvas.getBoundingClientRect();
          dragStart = {x: e.clientX - rect.left, y: e.clientY - rect.top};
          dragging = true;
        }
      };
      canvas.onmousemove = (e) => {
        if (panning && panStart) { panX = e.clientX - panStart.x; panY = e.clientY - panStart.y; draw(); return; }
        if (!dragging || !dragStart) return;
        const rect = canvas.getBoundingClientRect();
        const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
        const [ix1, iy1] = screenToImage(Math.min(dragStart.x, cx), Math.min(dragStart.y, cy));
        const [ix2, iy2] = screenToImage(Math.max(dragStart.x, cx), Math.max(dragStart.y, cy));
        const w = Math.max(0, ix2 - ix1), h = Math.max(0, iy2 - iy1);
        ocrRegionRect = {x: Math.max(0, ix1), y: Math.max(0, iy1), w, h};
        draw();
        document.getElementById("ocr-region-readout").textContent = `${ocrRegionRect.x}, ${ocrRegionRect.y}, ${w}×${h}`;
        document.getElementById("ocr-region-apply").disabled = (w < 2 || h < 2);
      };
      canvas.onmouseup = (e) => { if (e.button === 1) panning = false; if (e.button === 0) dragging = false; };
      canvas.oncontextmenu = (e) => e.preventDefault();
    };
    img.src = dataUri;
  }

  document.getElementById("ocr-region-apply").addEventListener("click", () => {
    if (!ocrRegionRect || !ocrRegionKey) return;
    document.getElementById("ocr-region-modal").style.display = "none";
    // Write the coords back to the region inputs
    const row = document.querySelector(`.vision-region-row input[data-vr-key="${ocrRegionKey}"]`)?.closest(".vision-region-row");
    if (row) {
      const inputs = row.querySelectorAll("input");
      inputs[0].value = ocrRegionRect.x;
      inputs[1].value = ocrRegionRect.y;
      inputs[2].value = ocrRegionRect.w;
      inputs[3].value = ocrRegionRect.h;
      // Save
      if (window.pywebview && pywebview.api) {
        pywebview.api.set_vision_region(ocrRegionKey, [ocrRegionRect.x, ocrRegionRect.y, ocrRegionRect.w, ocrRegionRect.h]);
      }
    }
    window.addLog(`[OCR] Region set for ${ocrRegionKey}: ${ocrRegionRect.x},${ocrRegionRect.y} ${ocrRegionRect.w}×${ocrRegionRect.h}`);
    ocrRegionKey = null; ocrRegionRect = null;
  });

  document.getElementById("ocr-region-cancel").addEventListener("click", () => {
    document.getElementById("ocr-region-modal").style.display = "none";
  });
  document.getElementById("ocr-region-cancel-btn").addEventListener("click", () => {
    document.getElementById("ocr-region-modal").style.display = "none";
  });
  document.getElementById("ocr-region-recapture").addEventListener("click", async () => {
    if (!window.pywebview || !pywebview.api || !ocrRegionKey) return;
    document.getElementById("ocr-region-modal").style.display = "none";
    // No screen switch needed: the backend reveals the game for the grab itself.
    const snap = await pywebview.api.get_roblox_snapshot();
    if (!snap.ok) { window.addLog("[OCR] Recapture failed."); return; }
    ocrCachedSnapshot = snap.data_uri;
    openRegionPicker(ocrRegionKey, ocrCachedSnapshot);
  });

  // ---- Vision regions ----
  async function loadVisionRegions() {
    if (!window.pywebview || !pywebview.api) return;
    const specs = await pywebview.api.get_vision_region_specs();
    const overrides = await pywebview.api.get_vision_regions();
    const list = document.getElementById("vision-regions-list");
    if (!list || !specs) return;
    list.innerHTML = specs.map(s => {
      const val = overrides[s.key] || s.default;
      return `<div class="vision-region-row">
        <span class="vr-label">${s.label}</span>
        <input type="number" value="${val[0]}" data-vr-key="${s.key}" data-vr-idx="0" title="x">
        <input type="number" value="${val[1]}" data-vr-key="${s.key}" data-vr-idx="1" title="y">
        <input type="number" value="${val[2]}" data-vr-key="${s.key}" data-vr-idx="2" title="w">
        <input type="number" value="${val[3]}" data-vr-key="${s.key}" data-vr-idx="3" title="h">
        <button class="btn btn--sm" data-vr-set="${s.key}" title="Set from Roblox screenshot">Set</button>
      </div>`;
    }).join("");
    list.querySelectorAll("input[data-vr-key]").forEach(inp => {
      inp.addEventListener("change", () => {
        if (!window.pywebview || !pywebview.api) return;
        const key = inp.dataset.vrKey;
        const row = inp.closest(".vision-region-row");
        const inputs = row.querySelectorAll("input");
        const box = [parseInt(inputs[0].value), parseInt(inputs[1].value), parseInt(inputs[2].value), parseInt(inputs[3].value)];
        pywebview.api.set_vision_region(key, box);
      });
    });
    // Set buttons — capture Roblox + draw region to set coords
    list.querySelectorAll("[data-vr-set]").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!window.pywebview || !pywebview.api) return;
        const key = btn.dataset.vrSet;
        // Use cached snapshot if available, otherwise capture
        if (ocrCachedSnapshot) {
          openRegionPicker(key, ocrCachedSnapshot);
          return;
        }
        btn.textContent = "...";
        const snap = await pywebview.api.get_roblox_snapshot();
        btn.textContent = "Set";
        if (!snap.ok) { window.addLog("[OCR] Capture failed — is Roblox running?"); return; }
        ocrCachedSnapshot = snap.data_uri;
        openRegionPicker(key, ocrCachedSnapshot);
      });
    });
  }

  document.getElementById("btn-vision-reset").addEventListener("click", async () => {
    if (!window.pywebview || !pywebview.api) return;
    await pywebview.api.reset_vision_regions();
    loadVisionRegions();
    window.addLog("Vision regions reset to defaults.");
  });

  document.getElementById("btn-vision-test-all").addEventListener("click", async () => {
    if (!window.pywebview || !pywebview.api) return;
    // Stays on this screen: test_ocr_all reveals the game, grabs one frame, and
    // re-hides it before the OCR pass runs off-thread.
    await pywebview.api.test_ocr_all();
  });

  // Populate gamemodes in the task builder mode dropdown
  window.addEventListener("pywebviewready", () => {
    if (window.pywebview && pywebview.api && pywebview.api.get_gamemodes) {
      pywebview.api.get_gamemodes().then((modes) => {
        tbMode.innerHTML = modes.map((m) => `<option value="${m}">${m}</option>`).join("");
      });
    }
  });

  // Slot toggle buttons for Challenge
  document.querySelectorAll(".slot-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      btn.classList.toggle("on");
      saveCurrentTask();
    });
  });

  // Called from Python's on_loaded after _app_root is set.
  window.onBackendReady = function () {
    loadSettings();
    loadGameKeybinds();
    loadOperationList();
    loadTasks();
    loadQueuePresets();
    loadVisionRegions();
  };

  // ---- Macro Manager ----
  const PHASES = ["pre_start", "battle", "loop_a", "loop_b"];
  let opPhases = { pre_start: [{ type: "walk_path", params: {}, mode: "auto", pathName: "" }], battle: [], loop_a: [], loop_b: [] };
  let opDirty = false;

  // List all place_unit blocks across phases as {n, name} for unit-index dropdowns.
  function listPlacedUnits() {
    const out = [];
    let n = 0;
    PHASES.forEach((phase) => {
      (opPhases[phase] || []).forEach((b) => {
        if (b.type === "place_unit") { n++; out.push({ n, name: b.params?.name || "" }); }
      });
    });
    return out;
  }

  // Build a unit-index dropdown (which placed unit this block acts on).
  function unitIndexSelect(b) {
    const units = listPlacedUnits();
    const cur = String(b.params?.index ?? "");
    const opts = units.map(u => `<option value="${u.n}"${String(u.n) === cur ? " selected" : ""}>#${u.n}${u.name ? " " + u.name : ""}</option>`).join("");
    return `<span class="blk-field"><span class="blk-field-label">Unit</span><select class="blk-select" data-field="params.index">${'<option value="">—</option>' + opts}</select></span>`;
  }

  // A labeled field wrapper (caption above the control).
  function blkField(label, inner) {
    return `<span class="blk-field"><span class="blk-field-label">${label}</span>${inner}</span>`;
  }

  function renderPhases() {
    PHASES.forEach((phase) => {
      const zone = document.getElementById("zone-" + phase);
      const count = document.getElementById("count-" + phase);
      const blocks = opPhases[phase] || [];
      count.textContent = blocks.length;
      if (!blocks.length) {
        zone.innerHTML = '<div class="phase-placeholder">Drag blocks here</div>';
        return;
      }
      zone.innerHTML = blocks.map((b, i) => {
        const isPinned = b.type === "walk_path";
        let fields = "";
        let removable = !isPinned;
        if (b.type === "walk_path") {
          // Pinned walk path: icon + Auto/Custom toggle + Sprint + Record
          fields = `<svg class="pinned-walk-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--teal)" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v4m0 12v4m-10-10h4m12 0h4"/></svg>
            <button class="btn btn--sm${b.mode === "auto" ? " btn--primary" : ""}" onclick="setWalkPathMode('${phase}',${i},'auto')">Auto</button>
            <button class="btn btn--sm${b.mode === "custom" ? " btn--primary" : ""}" onclick="setWalkPathMode('${phase}',${i},'custom')">Custom</button>
            <label class="check"><input type="checkbox" ${b.sprint ? "checked" : ""} data-field="sprint"><span class="check-box"></span>Sprint</label>`;
          if (b.mode === "custom") {
            fields += `<select class="setting-select" data-field="pathName" style="width:90px;height:22px;font-size:10px;" id="sel-walkpath-${phase}-${i}"><option value="">Pick path...</option></select>
              <button class="btn btn--sm" id="btn-walkrec-${phase}-${i}">Rec</button>
              <button class="btn btn--sm" id="btn-walktest-${phase}-${i}">Test</button>
              <button class="btn btn--sm btn--danger" id="btn-walkdel-${phase}-${i}" title="Delete walk path">✕</button>`;
          }
          fields += `<span class="block-once-badge">RUNS ONCE</span>`;
        } else if (b.type === "place_unit") {
          const hk = b.hotkey || "";
          // Compute this block's #N ordinal among place_unit blocks
          let ord = 0; for (const ph of PHASES) { for (const bb of (opPhases[ph]||[])) { if (bb.type === "place_unit") { ord++; if (bb === b) break; } } if (opPhases[ph].includes(b)) break; }
          fields = `<span class="unit-ord">#${ord}</span>`
            + blkField("Key", `<button class="btn btn--sm hotkey-capture" id="hk-${phase}-${i}" title="Unit slot hotkey">${hk ? hk.toUpperCase() : "Key"}</button>`)
            + blkField("X", `<input value="${b.params?.x || 0}" data-field="params.x" type="number">`)
            + blkField("Y", `<input value="${b.params?.y || 0}" data-field="params.y" type="number">`)
            + blkField("Position", `<button class="btn btn--sm" onclick="openPositionPicker('${phase}',${i})">Set</button>`)
            + blkField("Name", `<input value="${b.params?.name || ""}" data-field="params.name" style="width:80px;">`);
        } else if (b.type === "upgrade_unit") {
          fields = unitIndexSelect(b)
            + blkField("Times", `<input value="${b.params?.times || 1}" data-field="params.times" type="number" style="width:40px;">`)
            + `<label class="check"><input type="checkbox" ${b.autograde ? "checked" : ""} data-field="autograde"><span class="check-box"></span>Auto</label>`;
        } else if (b.type === "sell_unit") {
          fields = unitIndexSelect(b);
        } else if (b.type === "target_priority") {
          const prio = String(b.params?.priority || "Boss");
          const opts = ["First","Last","Strongest","Boss","Weakest","Shielded","Fastest","None"].map(p => `<option value="${p}"${p === prio ? " selected" : ""}>${p}</option>`).join("");
          fields = unitIndexSelect(b)
            + blkField("Target", `<select class="blk-select" data-field="params.priority">${opts}</select>`);
        } else if (b.type === "wait_ms") fields = blkField("Milliseconds", `<input value="${b.params?.ms || 500}" data-field="params.ms" type="number">`);
        else if (b.type === "wait_wave") fields = blkField("Wave", `<input value="${b.params?.wave || 1}" data-field="params.wave" type="number">`);
        else if (b.type === "leave_at_minute") fields = blkField("Minutes", `<input value="${b.params?.minutes || 10}" data-field="params.minutes" type="number">`);
        else if (b.type === "click") fields = blkField("X", `<input value="${b.params?.x || 0}" data-field="params.x" type="number">`) + blkField("Y", `<input value="${b.params?.y || 0}" data-field="params.y" type="number">`) + blkField("Position", `<button class="btn btn--sm" onclick="openPositionPicker('${phase}',${i})">Set</button>`);
        else if (b.type === "send_key") fields = blkField("Key", `<input value="${b.key || ""}" data-field="key" style="width:50px;">`) + blkField("Hold (ms)", `<input value="${b.params?.hold_ms || 0}" data-field="params.hold_ms" type="number" style="width:60px;">`);
        else if (b.type === "walk") fields = `<button class="btn btn--sm" id="btn-walk-rec-${phase}-${i}">Rec</button><button class="btn btn--sm" id="btn-walktest-${phase}-${i}">Test</button><button class="btn btn--sm btn--danger" id="btn-walkdel-${phase}-${i}" title="Delete walk path">✕</button><select class="setting-select" data-field="pathName" style="width:100px;height:22px;font-size:10px;" id="sel-walk-${phase}-${i}"><option value="">Pick path...</option></select><label class="check"><input type="checkbox" ${b.sprint ? "checked" : ""} data-field="sprint"><span class="check-box"></span>Sprint</label>`;
        else if (b.type === "record") fields = `<select class="setting-select" data-field="recordingName" style="width:110px;height:22px;font-size:10px;" id="sel-rec-${phase}-${i}"><option value="">Select...</option></select><button class="btn btn--sm" id="btn-record-${phase}-${i}">Rec</button><button class="btn btn--sm" id="btn-test-rec-${phase}-${i}">Test</button><button class="btn btn--sm btn--danger" id="btn-del-rec-${phase}-${i}" title="Delete recording">✕</button>`;
        else if (b.type === "detect") {
          const thenBlocks = (b.then || []);
          const elseBlocks = (b.else || []);
          return `<div class="block-row block-detect" data-phase="${phase}" data-idx="${i}" data-type="detect">
            <div class="detect-header">
              <span class="block-type">detect</span>
              <input placeholder="image" value="${b.image || ""}" data-field="image" style="width:80px;">
              <input placeholder="threshold" value="${b.threshold || 0.8}" data-field="threshold" type="number" step="0.05" style="width:55px;">
              <label class="check"><input type="checkbox" ${b.loop ? "checked" : ""} data-field="loop"><span class="check-box"></span>Loop</label>
              <span class="block-actions">
                <span class="block-once${b.once ? " on" : ""}" data-phase="${phase}" data-idx="${i}" title="Run Once">1×</span>
                <span class="block-clone" data-phase="${phase}" data-idx="${i}" title="Clone">⊕</span>
                <span class="block-remove" data-phase="${phase}" data-idx="${i}">&times;</span>
              </span>
            </div>
            <div class="detect-branches">
              <div class="detect-branch">
                <span class="detect-branch-label then-label">Then (found)</span>
                <div class="detect-dropzone" data-phase="${phase}" data-parent="${i}" data-branch="then">
                  ${thenBlocks.length ? thenBlocks.map((tb, ti) => `<div class="block-row" data-phase="${phase}" data-parent="${i}" data-branch="then" data-idx="${ti}" data-type="${tb.type}" draggable="true"><span class="block-type">${tb.type.replace(/_/g," ")}</span><span class="block-remove" data-phase="${phase}" data-parent="${i}" data-branch="then" data-idx="${ti}">&times;</span></div>`).join("") : '<div class="phase-placeholder" style="padding:6px;">Drop here</div>'}
                </div>
              </div>
              <div class="detect-branch">
                <span class="detect-branch-label else-label">Else (not found)</span>
                <div class="detect-dropzone" data-phase="${phase}" data-parent="${i}" data-branch="else">
                  ${elseBlocks.length ? elseBlocks.map((eb, ei) => `<div class="block-row" data-phase="${phase}" data-parent="${i}" data-branch="else" data-idx="${ei}" data-type="${eb.type}" draggable="true"><span class="block-type">${eb.type.replace(/_/g," ")}</span><span class="block-remove" data-phase="${phase}" data-parent="${i}" data-branch="else" data-idx="${ei}">&times;</span></div>`).join("") : '<div class="phase-placeholder" style="padding:6px;">Drop here</div>'}
                </div>
              </div>
            </div>
          </div>`;
        }
        // Block actions: Once toggle + Clone + Remove (not on pinned)
        const actions = isPinned ? "" : `<span class="block-actions">
          <span class="block-once${b.once ? " on" : ""}" data-phase="${phase}" data-idx="${i}" title="Run Once">1×</span>
          <span class="block-clone" data-phase="${phase}" data-idx="${i}" title="Clone">⊕</span>
          <span class="block-remove" data-phase="${phase}" data-idx="${i}">&times;</span>
        </span>`;
        return `<div class="block-row${isPinned ? " pinned" : ""}" data-phase="${phase}" data-idx="${i}" data-type="${b.type}" draggable="${isPinned ? "false" : "true"}">
          <span class="block-type">${b.type.replace(/_/g, " ")}</span>
          <span class="block-fields">${fields}</span>
          ${actions}
        </div>`;
      }).join("");

      // Wire inline field edits
      zone.querySelectorAll("input[data-field], select[data-field]").forEach((inp) => {
        inp.addEventListener("change", (e) => {
          const row = e.target.closest(".block-row");
          const ph = row.dataset.phase;
          const idx = parseInt(row.dataset.idx);
          const parentIdx = row.dataset.parent !== undefined ? parseInt(row.dataset.parent) : null;
          const branch = row.dataset.branch || null;
          const field = e.target.dataset.field;
          let val;
          if (e.target.type === "number") val = Number(e.target.value);
          else if (e.target.type === "checkbox") val = e.target.checked;
          else val = e.target.value;

          let targetBlock;
          if (parentIdx !== null && branch) {
            targetBlock = opPhases[ph][parentIdx][branch]?.[idx];
          } else {
            targetBlock = opPhases[ph][idx];
          }
          if (!targetBlock) return;

          if (field.startsWith("params.")) {
            const key = field.split(".")[1];
            targetBlock.params = targetBlock.params || {};
            targetBlock.params[key] = val;
          } else {
            targetBlock[field] = val;
          }
          opDirty = true;
          // Re-render if mode changed (walk_path shows/hides path name input)
          if (field === "mode") renderPhases();
        });
      });

      // Wire remove buttons (including nested detect branches)
      zone.querySelectorAll(".block-remove").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const ph = btn.dataset.phase;
          const parentIdx = btn.dataset.parent !== undefined ? parseInt(btn.dataset.parent) : null;
          const branch = btn.dataset.branch || null;
          const idx = parseInt(btn.dataset.idx);
          if (parentIdx !== null && branch) {
            opPhases[ph][parentIdx][branch].splice(idx, 1);
          } else {
            opPhases[ph].splice(idx, 1);
          }
          opDirty = true;
          renderPhases();
        });
      });

      // Wire clone buttons
      zone.querySelectorAll(".block-clone").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const ph = btn.dataset.phase;
          const idx = parseInt(btn.dataset.idx);
          const original = opPhases[ph][idx];
          const clone = JSON.parse(JSON.stringify(original));
          delete clone.once; // cloned blocks start without "once"
          opPhases[ph].splice(idx + 1, 0, clone);
          opDirty = true;
          renderPhases();
        });
      });

      // Wire once toggle buttons
      zone.querySelectorAll(".block-once").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const ph = btn.dataset.phase;
          const idx = parseInt(btn.dataset.idx);
          opPhases[ph][idx].once = !opPhases[ph][idx].once;
          opDirty = true;
          renderPhases();
        });
      });

      // Wire hotkey capture buttons (Place Unit)
      zone.querySelectorAll(".hotkey-capture").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          btn.textContent = "...";
          btn.classList.add("capturing");
          if (window.pywebview && pywebview.api) pywebview.api.begin_hotkey_capture();
          const handler = (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            document.removeEventListener("keydown", handler, true);
            btn.classList.remove("capturing");
            if (window.pywebview && pywebview.api) pywebview.api.end_hotkey_capture();
            const key = ev.key.length === 1 ? ev.key : ev.key;
            btn.textContent = key.toUpperCase();
            // Parse phase/idx from btn id: hk-<phase>-<idx>
            const parts = btn.id.replace("hk-", "").split("-");
            const ph = parts[0];
            const idx = parseInt(parts[1]);
            opPhases[ph][idx].hotkey = key.toLowerCase();
            opDirty = true;
          };
          document.addEventListener("keydown", handler, true);
        });
      });

      // Wire drag reorder on block rows
      zone.querySelectorAll(".block-row[draggable='true']").forEach((row) => {
        row.addEventListener("dragstart", (e) => {
          e.stopPropagation();
          row.classList.add("dragging");
          e.dataTransfer.setData("application/x-block-move", JSON.stringify({
            phase: row.dataset.phase,
            idx: parseInt(row.dataset.idx)
          }));
          e.dataTransfer.effectAllowed = "move";
        });
        row.addEventListener("dragend", () => {
          row.classList.remove("dragging");
          document.querySelectorAll(".drop-placeholder").forEach((p) => p.remove());
          document.querySelectorAll(".phase-section.drag-active").forEach((s) => s.classList.remove("drag-active"));
          document.querySelectorAll(".phase-dropzone.drag-over").forEach((z) => z.classList.remove("drag-over"));
        });
        row.addEventListener("dragover", (e) => {
          e.preventDefault();
          e.stopPropagation();
          const moveData = e.dataTransfer.types.includes("application/x-block-move") || e.dataTransfer.types.includes("text/plain");
          if (!moveData) return;
          const rect = row.getBoundingClientRect();
          const midY = rect.top + rect.height / 2;
          const after = e.clientY > midY;
          // Reuse a single placeholder per zone
          let placeholder = zone.querySelector(".drop-placeholder");
          if (!placeholder) {
            placeholder = document.createElement("div");
            placeholder.className = "drop-placeholder";
            zone.appendChild(placeholder);
            requestAnimationFrame(() => placeholder.classList.add("open"));
          }
          if (after) { if (row.nextElementSibling !== placeholder) row.after(placeholder); }
          else { if (row.previousElementSibling !== placeholder) row.before(placeholder); }
          if (!placeholder.classList.contains("open")) {
            requestAnimationFrame(() => placeholder.classList.add("open"));
          }
        });
        row.addEventListener("dragleave", (e) => {
          // Only remove if leaving the zone entirely (not entering another row)
        });
        row.addEventListener("drop", (e) => {
          e.preventDefault();
          e.stopPropagation();
          const ph = zone.querySelector(".drop-placeholder");
          if (ph) ph.remove();
          const raw = e.dataTransfer.getData("application/x-block-move");
          if (!raw) return;
          const src = JSON.parse(raw);
          const rect = row.getBoundingClientRect();
          const midY = rect.top + rect.height / 2;
          const after = e.clientY > midY;
          const destPhase = row.dataset.phase;
          const destIdx = parseInt(row.dataset.idx) + (after ? 1 : 0);

          // Remove from source
          const [moved] = opPhases[src.phase].splice(src.idx, 1);
          if (!moved) return;
          // Adjust dest index if same phase and removing shifted it
          let insertIdx = destIdx;
          if (src.phase === destPhase && src.idx < destIdx) insertIdx--;
          opPhases[destPhase].splice(insertIdx, 0, moved);
          opDirty = true;
          renderPhases();
        });
      });

      // Wire detect branch drop zones
      zone.querySelectorAll(".detect-dropzone").forEach((dz) => {
        dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag-over"); });
        dz.addEventListener("dragleave", () => { dz.classList.remove("drag-over"); });
        dz.addEventListener("drop", (e) => {
          e.preventDefault();
          e.stopPropagation();
          dz.classList.remove("drag-over");
          const type = e.dataTransfer.getData("text/plain");
          if (!type || type === "detect" || type === "walk_path") return; // no nesting detects or walk_path
          const parentIdx = parseInt(dz.dataset.parent);
          const branch = dz.dataset.branch;
          const ph = dz.dataset.phase;
          const block = { type, params: {} };
          if (!opPhases[ph][parentIdx][branch]) opPhases[ph][parentIdx][branch] = [];
          opPhases[ph][parentIdx][branch].push(block);
          opDirty = true;
          renderPhases();
        });
      });

      // Wire walk recording buttons (both walk blocks and walk_path custom)
      zone.querySelectorAll("[id^='btn-walk-rec-'], [id^='btn-walkrec-']").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.id;
          let ph, idx;
          if (id.startsWith("btn-walkrec-")) {
            const parts = id.replace("btn-walkrec-", "").split("-");
            ph = parts[0]; idx = parseInt(parts[1]);
          } else {
            const parts = id.replace("btn-walk-rec-", "").split("-");
            ph = parts[0]; idx = parseInt(parts[1]);
          }
          startWalkRecording(ph, idx);
        });
      });
      // Wire walk test buttons
      zone.querySelectorAll("[id^='btn-walktest-']").forEach((btn) => {
        btn.addEventListener("click", () => {
          const parts = btn.id.replace("btn-walktest-", "").split("-");
          const ph = parts[0];
          const idx = parseInt(parts[1]);
          testWalkPath(ph, idx);
        });
      });
      // Wire walk delete buttons
      zone.querySelectorAll("[id^='btn-walkdel-']").forEach((btn) => {
        btn.addEventListener("click", () => {
          const parts = btn.id.replace("btn-walkdel-", "").split("-");
          deleteWalkPath(parts[0], parseInt(parts[1]));
        });
      });
      // Wire input recording buttons
      zone.querySelectorAll("[id^='btn-record-']").forEach((btn) => {
        btn.addEventListener("click", () => {
          const parts = btn.id.split("-");
          const ph = parts[2];
          const idx = parseInt(parts[3]);
          startInputRecording(ph, idx);
        });
      });
      // Wire test recording buttons
      zone.querySelectorAll("[id^='btn-test-rec-']").forEach((btn) => {
        btn.addEventListener("click", () => {
          const parts = btn.id.split("-");
          const ph = parts[3];
          const idx = parseInt(parts[4]);
          testRecording(ph, idx);
        });
      });
      // Wire delete recording buttons
      zone.querySelectorAll("[id^='btn-del-rec-']").forEach((btn) => {
        btn.addEventListener("click", () => {
          const parts = btn.id.split("-");
          const ph = parts[3];
          const idx = parseInt(parts[4]);
          deleteRecording(ph, idx);
        });
      });
      // Populate recording dropdowns
      zone.querySelectorAll("[id^='sel-rec-']").forEach((sel) => {
        const parts = sel.id.split("-");
        const ph = parts[2];
        const idx = parseInt(parts[3]);
        const current = opPhases[ph][idx].recordingName || "";
        populateRecordingSelect(sel, current);
      });
      // Populate walk path dropdowns (both walk_path custom and walk blocks)
      zone.querySelectorAll("[id^='sel-walkpath-'], [id^='sel-walk-']").forEach((sel) => {
        const parts = sel.id.split("-");
        const ph = parts[1] === "walkpath" ? parts[2] : parts[2];
        const idx = parseInt(parts[1] === "walkpath" ? parts[3] : parts[3]);
        // For sel-walkpath-<phase>-<idx> and sel-walk-<phase>-<idx>
        const idParts = sel.id.replace("sel-", "").split("-");
        const prefix = idParts[0]; // "walkpath" or "walk"
        const phKey = idParts[1];
        const idxNum = parseInt(idParts[2]);
        const current = opPhases[phKey]?.[idxNum]?.pathName || "";
        populateWalkPathSelect(sel, current);
      });
    });
  }

  // Drag and drop from palette to phases
  document.querySelectorAll(".palette-block").forEach((el) => {
    el.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", el.dataset.type);
    });
  });

  PHASES.forEach((phase) => {
    const zone = document.getElementById("zone-" + phase);
    const section = zone.closest(".phase-section");
    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("drag-over");
      if (section) section.classList.add("drag-active");
    });
    zone.addEventListener("dragleave", (e) => {
      if (!zone.contains(e.relatedTarget)) {
        zone.classList.remove("drag-over");
        if (section) section.classList.remove("drag-active");
      }
    });
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("drag-over");
      if (section) section.classList.remove("drag-active");
      const ph = zone.querySelector(".drop-placeholder");
      if (ph) ph.remove();

      // Cross-phase block move (reorder from another phase or within when dropped on empty area)
      const moveRaw = e.dataTransfer.getData("application/x-block-move");
      if (moveRaw) {
        const src = JSON.parse(moveRaw);
        const [moved] = opPhases[src.phase].splice(src.idx, 1);
        if (moved) {
          opPhases[phase].push(moved);
          opDirty = true;
          renderPhases();
        }
        return;
      }

      // New block from palette
      const type = e.dataTransfer.getData("text/plain");
      if (!type) return;
      const block = { type, params: {} };
      if (type === "place_unit") block.params = { name: "", x: 0, y: 0 };
      else if (type === "wait_ms") block.params = { ms: 500 };
      else if (type === "wait_wave") block.params = { wave: 1 };
      else if (type === "leave_at_minute") block.params = { minutes: 10 };
      else if (type === "click") block.params = { x: 0, y: 0 };
      else if (type === "send_key") { block.key = ""; block.params = { hold_ms: 0 }; }
      else if (type === "upgrade_unit" || type === "sell_unit" || type === "target_priority") block.params = { x: 0, y: 0, times: 1 };
      else if (type === "walk") { block.pathName = ""; block.params = {}; }
      else if (type === "record") { block.recordingName = ""; block.params = {}; }
      else if (type === "detect") { block.image = ""; block.threshold = 0.8; block.loop = false; block.then = []; block.else = []; }
      opPhases[phase].push(block);
      opDirty = true;
      renderPhases();
    });
  });

  // Save / Load / New / Delete
  const opName = document.getElementById("op-name");
  const opLoad = document.getElementById("op-load");

  async function loadOperationList() {
    if (!window.pywebview || !pywebview.api) return;
    const names = await pywebview.api.list_operations();
    opLoad.innerHTML = '<option value="">Load...</option>' + names.map((n) => `<option value="${n}">${n}</option>`).join("");
    // Also populate the task builder's macro dropdown
    tbMacro.innerHTML = '<option value="">No Macro</option>' + names.map((n) => `<option value="${n}">${n}</option>`).join("");
  }

  document.getElementById("btn-op-save").addEventListener("click", async () => {
    const name = opName.value.trim();
    if (!name || !window.pywebview || !pywebview.api) return;
    await pywebview.api.save_operation(name, opPhases);
    opDirty = false;
    window.addLog("Saved operation: " + name);
    loadOperationList();
  });

  document.getElementById("btn-op-new").addEventListener("click", () => {
    opName.value = "";
    opPhases = { pre_start: [{ type: "walk_path", params: {}, mode: "auto", pathName: "" }], battle: [], loop_a: [], loop_b: [] };
    opDirty = false;
    renderPhases();
  });

  document.getElementById("btn-op-clear").addEventListener("click", () => {
    // Reset all phases to default (only walk_path in pre_start)
    opPhases = { pre_start: [{ type: "walk_path", params: {}, mode: "auto", pathName: "" }], battle: [], loop_a: [], loop_b: [] };
    opDirty = true;
    renderPhases();
  });

  document.getElementById("btn-op-delete").addEventListener("click", async () => {
    const name = opName.value.trim();
    if (!name || !window.pywebview || !pywebview.api) return;
    await pywebview.api.delete_operation(name);
    opName.value = "";
    opPhases = { pre_start: [], battle: [], loop_a: [], loop_b: [] };
    opDirty = false;
    renderPhases();
    loadOperationList();
    window.addLog("Deleted operation: " + name);
  });

  opLoad.addEventListener("change", async () => {
    const name = opLoad.value;
    if (!name || !window.pywebview || !pywebview.api) return;
    const data = await pywebview.api.load_operation(name);
    opName.value = data.name || name;
    opPhases = data.phases || { pre_start: [], battle: [], loop_a: [], loop_b: [] };
    // Ensure pinned walk_path block exists in pre_start
    if (!opPhases.pre_start || !opPhases.pre_start.length || opPhases.pre_start[0].type !== "walk_path") {
      const walkBlock = { type: "walk_path", params: {}, mode: "auto", pathName: "", sprint: false };
      opPhases.pre_start = [walkBlock, ...(opPhases.pre_start || [])];
    }
    opDirty = false;
    renderPhases();
    opLoad.value = "";
  });

  // ---- Settings screen ----
  const settingsContent = document.getElementById("settings-content");

  // Category switching
  const catButtons = document.querySelectorAll(".settings-nav-btn[data-cat]");
  const categories = document.querySelectorAll(".settings-category[data-cat]");

  function switchSettingsCategory(cat) {
    categories.forEach((el) => el.style.display = (cat === "all" || el.dataset.cat === cat) ? "" : "none");
    catButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.cat === cat));
  }

  catButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchSettingsCategory(btn.dataset.cat));
  });

  // Search
  document.getElementById("settings-search").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    if (q) switchSettingsCategory("all");
    settingsContent.querySelectorAll(".settings-category").forEach((cat) => {
      let hasMatch = false;
      cat.querySelectorAll(".setting-row").forEach((row) => {
        const text = row.textContent.toLowerCase();
        const match = !q || text.includes(q);
        row.style.display = match ? "" : "none";
        if (match) hasMatch = true;
      });
      // Hide the entire section header if no rows match
      const header = cat.querySelector(".page-header");
      if (q) {
        cat.style.display = hasMatch ? "" : "none";
      } else {
        cat.style.display = "";
        cat.querySelectorAll(".setting-row").forEach((row) => { row.style.display = ""; });
      }
    });
  });

  // Auto-save: every input/checkbox/select with data-key saves immediately
  function wireAutoSave() {
    settingsContent.querySelectorAll("[data-key]").forEach((el) => {
      const key = el.dataset.key;
      const event = el.type === "checkbox" ? "change" : "change";
      el.addEventListener(event, () => {
        if (!window.pywebview || !pywebview.api) return;
        let val;
        if (el.type === "checkbox") val = el.checked;
        else if (el.type === "number") val = Number(el.value);
        else val = el.value;
        pywebview.api.set_setting(key, val);
      });
      // Also save text inputs on blur (in case user doesn't press Enter)
      if (el.type === "text") {
        el.addEventListener("blur", () => {
          if (!window.pywebview || !pywebview.api) return;
          pywebview.api.set_setting(key, el.value);
        });
      }
    });
  }

  async function loadSettings() {
    if (!window.pywebview || !pywebview.api) return;
    try {
      const s = await pywebview.api.get_settings();
      // Populate general fields
      const fields = settingsContent.querySelectorAll("[data-key]");
      fields.forEach((el) => {
        const val = s[el.dataset.key];
        if (val === undefined) return;
        if (el.type === "checkbox") el.checked = !!val;
        else el.value = val;
      });
    } catch (e) {}

    // Hotkeys
    try {
      const hk = await pywebview.api.get_hotkeys();
      const hkList = document.getElementById("hotkeys-list");
      if (hk && Object.keys(hk).length) {
        hkList.innerHTML = Object.entries(hk).map(([action, display]) =>
          `<div class="setting-row">
            <div class="setting-info"><span class="setting-name">${action.replace(/_/g, " ")}</span></div>
            <button class="hotkey-btn" data-action="${action}">${display || "Unbound"}</button>
          </div>`
        ).join("");
        // Wire key capture
        hkList.querySelectorAll(".hotkey-btn").forEach((btn) => {
          btn.addEventListener("click", () => {
            btn.textContent = "Press a key...";
            btn.classList.add("capturing");
            if (window.pywebview && pywebview.api) pywebview.api.begin_hotkey_capture();
            const handler = (e) => {
              e.preventDefault();
              e.stopPropagation();
              document.removeEventListener("keydown", handler, true);
              btn.classList.remove("capturing");
              const vk = e.keyCode;
              const ctrl = e.ctrlKey;
              const shift = e.shiftKey;
              const alt = e.altKey;
              const display = (ctrl ? "Ctrl + " : "") + (shift ? "Shift + " : "") + (alt ? "Alt + " : "") + e.key.toUpperCase();
              btn.textContent = display;
              if (window.pywebview && pywebview.api) {
                pywebview.api.set_hotkey(btn.dataset.action, vk, ctrl, shift, alt);
                pywebview.api.end_hotkey_capture();
              }
            };
            document.addEventListener("keydown", handler, true);
          });
        });
      }
    } catch (e) {}

    // Delays
    try {
      const delays = await pywebview.api.get_delays();
      const dList = document.getElementById("delays-list");
      if (delays && Object.keys(delays).length) {
        dList.innerHTML = Object.entries(delays).map(([key, val]) =>
          `<div class="setting-row"><div class="setting-info"><span class="setting-name">${key.replace(/_/g, " ")}</span></div><input type="number" class="setting-input" value="${val}" step="0.1" style="width:80px;" data-delay-key="${key}"></div>`
        ).join("");
        dList.querySelectorAll("[data-delay-key]").forEach((inp) => {
          inp.addEventListener("change", () => {
            if (!window.pywebview || !pywebview.api) return;
            pywebview.api.set_delay(inp.dataset.delayKey, parseFloat(inp.value) || 0);
          });
        });
      }
    } catch (e) {}
  }

  document.getElementById("btn-reset-hotkeys").addEventListener("click", async () => {
    if (!window.pywebview || !pywebview.api) return;
    const r = await pywebview.api.reset_hotkeys();
    if (r.ok) { loadSettings(); window.addLog("Hotkeys reset to defaults."); }
  });

  // Game keybinds: load + capture
  async function loadGameKeybinds() {
    if (!window.pywebview || !pywebview.api) return;
    try {
      const s = await pywebview.api.get_settings();
      const gk = s.game_keybinds || {};
      document.querySelectorAll("[data-game-key]").forEach((btn) => {
        const key = btn.dataset.gameKey;
        if (gk[key]) btn.textContent = gk[key].toUpperCase();
      });
    } catch (e) {}
  }

  document.querySelectorAll("[data-game-key]").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.textContent = "...";
      btn.classList.add("capturing");
      if (window.pywebview && pywebview.api) pywebview.api.begin_hotkey_capture();
      const handler = (e) => {
        e.preventDefault();
        e.stopPropagation();
        document.removeEventListener("keydown", handler, true);
        btn.classList.remove("capturing");
        const key = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase();
        btn.textContent = key.toUpperCase();
        if (window.pywebview && pywebview.api) {
          pywebview.api.set_game_keybind(btn.dataset.gameKey, key);
          pywebview.api.end_hotkey_capture();
        }
      };
      document.addEventListener("keydown", handler, true);
    });
  });

  wireAutoSave();

  // ---- Image Manager Modal ----
  let imData = null;
  let imCategory = "all";
  const imModal = document.getElementById("im-modal");

  // Helper: restore game only if on Dashboard
  function restoreGameIfDashboard() {
    const dash = document.getElementById("screen-dashboard");
    if (dash && dash.classList.contains("active") && window.pywebview && pywebview.api) {
      pywebview.api.set_game_visible(true);
    }
  }

  window.openImageManager = async function () {
    // Toggle: if already open, close it
    if (imModal.style.display === "flex") {
      imModal.style.display = "none";
      restoreGameIfDashboard();
      return;
    }
    // Hide the game so the modal isn't behind it
    if (window.pywebview && pywebview.api) pywebview.api.set_game_visible(false);
    imModal.style.display = "flex";
    if (!window.pywebview || !pywebview.api) return;
    const result = await pywebview.api.list_vision_templates();
    if (!result.ok) return;
    imData = result;
    renderImTabs();
    renderImGrid();
  };

  document.getElementById("im-close").addEventListener("click", () => {
    imModal.style.display = "none";
    restoreGameIfDashboard();
  });
  document.getElementById("im-capture").addEventListener("click", async () => {
    if (!window.pywebview || !pywebview.api) return;
    // get_roblox_snapshot reveals the game itself when the current screen hides it.
    const r = await pywebview.api.get_roblox_snapshot();
    if (r.ok) window.addLog("[Image Manager] Captured Roblox screen.");
    else window.addLog("[Image Manager] Capture failed: " + (r.reason || "error"));
  });

  document.getElementById("im-filter").addEventListener("input", () => renderImGrid());

  function renderImTabs() {
    if (!imData) return;
    const tabsEl = document.getElementById("im-tabs");
    if (!tabsEl) return;
    const cats = [{ key: "all", label: "All" }].concat(imData.categories.map((c) => ({ key: c.key, label: c.label })));
    tabsEl.innerHTML = cats.map((c) =>
      `<button class="pos-tab${c.key === imCategory ? " active" : ""}" data-cat="${c.key}">${c.label}</button>`
    ).join("");
    tabsEl.querySelectorAll(".pos-tab").forEach((btn) => {
      btn.addEventListener("click", () => { imCategory = btn.dataset.cat; renderImTabs(); renderImGrid(); });
    });
  }

  function renderImGrid() {
    if (!imData) return;
    const gridEl = document.getElementById("im-grid");
    if (!gridEl) return;
    const filterEl = document.getElementById("im-filter");
    const q = (filterEl ? filterEl.value : "").trim().toLowerCase();
    let items = [];
    imData.categories.forEach((cat) => {
      if (imCategory !== "all" && cat.key !== imCategory) return;
      cat.names.forEach((img) => {
        if (q && !img.name.toLowerCase().includes(q)) return;
        items.push({ ...img, catKey: cat.key, catLabel: cat.label });
      });
    });
    gridEl.innerHTML = items.map((img) => `
      <div class="im-card${img.missing ? " im-card-missing" : ""}">
        <div class="im-card-header">
          <span class="im-card-cat">${img.catKey}</span>
          <span class="im-card-name">${img.name}</span>
          ${img.missing ? '<span class="im-missing-badge">MISSING</span>' : ''}
          <button class="im-card-add" data-cat="${img.catKey}" data-name="${img.name}" title="Capture &amp; add">+</button>
        </div>
        ${img.missing
          ? '<div class="im-card-missing-body">Capture from Roblox to add this template</div>'
          : `<img class="im-card-thumb" src="${img.data_uri}" alt="${img.name}">`}
        <div class="im-card-slider">
          <span>Match</span>
          <input type="range" min="0.50" max="1.00" step="0.01" value="${img.threshold}" data-name="${img.name}">
          <span class="im-val">${img.threshold.toFixed(2)}</span>
          ${!img.missing ? `<button class="btn btn--sm" data-test-image="${img.catKey}/${img.file}" title="Test search">Test</button>` : ''}
        </div>
      </div>
    `).join("");
    // Wire sliders
    gridEl.querySelectorAll('input[type="range"]').forEach((slider) => {
      slider.addEventListener("input", (e) => {
        e.target.closest(".im-card-slider").querySelector(".im-val").textContent = parseFloat(e.target.value).toFixed(2);
      });
      slider.addEventListener("change", (e) => {
        if (!window.pywebview || !pywebview.api) return;
        pywebview.api.set_image_threshold(e.target.dataset.name, parseFloat(e.target.value));
      });
    });
    // Wire + buttons (capture & crop)
    gridEl.querySelectorAll(".im-card-add").forEach((btn) => {
      btn.addEventListener("click", () => startImageCapture(btn.dataset.cat, btn.dataset.name));
    });
    // Wire test buttons
    gridEl.querySelectorAll("[data-test-image]").forEach((btn) => {
      btn.addEventListener("click", () => testImageSearch(btn.dataset.testImage));
    });
  }

  // ---- Image capture + crop flow ----
  let cropTarget = null; // {category, name}

  async function testImageSearch(imagePath) {
    if (!window.pywebview || !pywebview.api) return;
    // Hide modal, show game
    imModal.style.display = "none";
    if (pywebview.api.set_game_visible) pywebview.api.set_game_visible(true);
    switchScreen("dashboard");
    await new Promise(r => setTimeout(r, 400));
    window.addLog("[Image Test] Searching for: " + imagePath);
    const r = await pywebview.api.test_image_search(imagePath);
    if (r.ok) {
      window.addLog(`[Image Test] Found! Score: ${r.score.toFixed(3)} at (${r.x}, ${r.y})`);
    } else {
      window.addLog(`[Image Test] Not found. Best: ${r.best ? r.best.toFixed(3) : "—"} (threshold: ${r.threshold || 0.70})`);
    }
    // Return to image manager
    if (pywebview.api.set_game_visible) pywebview.api.set_game_visible(false);
    imModal.style.display = "flex";
  }
  let cropImage = null;
  let cropRect = null; // {x, y, w, h} in image coords
  let cropDragging = false;
  let cropStart = null;

  async function startImageCapture(category, name) {
    cropTarget = { category, name };
    if (!window.pywebview || !pywebview.api) return;
    // The backend reveals the game for the grab and re-hides it, so the modal
    // only has to get out of the way of the crop view that follows.
    imModal.style.display = "none";
    const result = await pywebview.api.get_roblox_snapshot();
    if (!result.ok) {
      window.addLog("[Image Manager] Capture failed: " + (result.reason || "error"));
      imModal.style.display = "flex";
      return;
    }
    // Show crop modal
    showCropView(result.data_uri, name);
  }

  function showCropView(dataUri, name) {
    const img = new Image();
    img.onload = () => {
      cropImage = img;
      cropRect = null;
      // Reuse the Image Manager modal as the crop view
      imModal.style.display = "flex";
      const body = imModal.querySelector(".modal-body");
      body.innerHTML = `
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
          <button class="btn btn--sm" id="crop-back">← Library</button>
          <span style="font-size:11px; color:var(--text-muted);">Draw a box around the element to crop</span>
          <span class="pos-readout" id="crop-readout" style="margin-left:auto;">No selection</span>
        </div>
        <div style="flex:1; min-height:400px; display:flex; align-items:center; justify-content:center; overflow:hidden; border:1px solid var(--border);">
          <canvas id="crop-canvas" style="cursor:crosshair; display:block; max-width:100%; max-height:100%;"></canvas>
        </div>
        <div style="display:flex; align-items:center; gap:8px; margin-top:8px;">
          <span style="font-size:12px; font-weight:600; color:var(--text);">${name}</span>
          <button class="btn btn--sm" id="crop-retake">Retake</button>
          <button class="btn btn--sm btn--primary" id="crop-save" style="margin-left:auto;" disabled>Save Crop</button>
        </div>
      `;
      const canvas = document.getElementById("crop-canvas");
      const ctx = canvas.getContext("2d");
      const wrap = canvas.parentElement;
      // Use the wrap's actual size (flex:1 + min-height gives it real dimensions)
      const wrapW = wrap.clientWidth || 860;
      const wrapH = wrap.clientHeight || 400;
      const scale = Math.min(wrapW / img.naturalWidth, wrapH / img.naturalHeight, 1);
      canvas.width = Math.floor(img.naturalWidth * scale);
      canvas.height = Math.floor(img.naturalHeight * scale);
      canvas.dataset.scale = scale;

      let zoom = 1.0; // 1.0 = fit to container
      let panX = 0, panY = 0;
      let panning = false, panStart = null;

      // Convert screen (canvas) coords to image-pixel coords
      function screenToImage(sx, sy) {
        const ix = (sx - panX) / zoom;
        const iy = (sy - panY) / zoom;
        // Canvas is drawn at `scale` of the original image, so canvas px / scale = image px
        return [Math.round(ix / scale), Math.round(iy / scale)];
      }

      function drawCrop() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.save();
        ctx.translate(panX, panY);
        ctx.scale(zoom, zoom);
        ctx.drawImage(img, 0, 0, img.naturalWidth * scale, img.naturalHeight * scale);
        if (cropRect) {
          ctx.strokeStyle = "#8b5cf6";
          ctx.lineWidth = 2 / zoom;
          ctx.strokeRect(cropRect.x * scale, cropRect.y * scale, cropRect.w * scale, cropRect.h * scale);
          ctx.fillStyle = "rgba(139, 92, 246, 0.15)";
          ctx.fillRect(cropRect.x * scale, cropRect.y * scale, cropRect.w * scale, cropRect.h * scale);
        }
        ctx.restore();
      }
      drawCrop();

      // Scroll wheel zoom toward cursor
      canvas.addEventListener("wheel", (e) => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const oldZoom = zoom;
        const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        zoom = Math.max(0.5, Math.min(5.0, zoom * factor));
        panX = mx - (mx - panX) * (zoom / oldZoom);
        panY = my - (my - panY) * (zoom / oldZoom);
        drawCrop();
      }, { passive: false });

      // Middle mouse button pan
      canvas.addEventListener("mousedown", (e) => {
        if (e.button === 1) { // middle
          e.preventDefault();
          panning = true;
          panStart = { x: e.clientX - panX, y: e.clientY - panY };
          return;
        }
        if (e.button === 0) { // left = draw crop
          const rect = canvas.getBoundingClientRect();
          cropStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };
          cropDragging = true;
        }
      });
      canvas.addEventListener("mousemove", (e) => {
        if (panning && panStart) {
          panX = e.clientX - panStart.x;
          panY = e.clientY - panStart.y;
          drawCrop();
          return;
        }
        if (!cropDragging || !cropStart) return;
        const rect = canvas.getBoundingClientRect();
        const cx = e.clientX - rect.left;
        const cy = e.clientY - rect.top;
        const [ix1, iy1] = screenToImage(Math.min(cropStart.x, cx), Math.min(cropStart.y, cy));
        const [ix2, iy2] = screenToImage(Math.max(cropStart.x, cx), Math.max(cropStart.y, cy));
        const w = Math.max(0, ix2 - ix1);
        const h = Math.max(0, iy2 - iy1);
        cropRect = { x: Math.max(0, ix1), y: Math.max(0, iy1), w, h };
        drawCrop();
        document.getElementById("crop-readout").textContent = `${w}×${h}`;
        document.getElementById("crop-save").disabled = (w < 4 || h < 4);
      });
      canvas.addEventListener("mouseup", (e) => {
        if (e.button === 1) panning = false;
        if (e.button === 0) cropDragging = false;
      });
      // Prevent context menu on middle click
      canvas.addEventListener("contextmenu", (e) => e.preventDefault());

      document.getElementById("crop-back").addEventListener("click", () => {
        // Restore the library view inside the modal body
        const body = imModal.querySelector(".modal-body");
        body.innerHTML = `<div id="im-tabs" class="pos-tabs"></div><div id="im-grid" class="im-grid"></div>`;
        // Re-bind the global references to the new DOM elements
        Object.defineProperty(window, '_imGrid', { value: document.getElementById("im-grid"), writable: true });
        Object.defineProperty(window, '_imTabs', { value: document.getElementById("im-tabs"), writable: true });
        // Re-render using cached data
        renderImTabs();
        renderImGrid();
        if (window.pywebview && pywebview.api) pywebview.api.set_game_visible(false);
      });
      document.getElementById("crop-retake").addEventListener("click", () => startImageCapture(cropTarget.category, cropTarget.name));
      document.getElementById("crop-save").addEventListener("click", async () => {
        if (!cropRect || !cropTarget || !window.pywebview || !pywebview.api) return;
        const r = await pywebview.api.save_image_crop(cropTarget.category, cropTarget.name, cropRect.x, cropRect.y, cropRect.w, cropRect.h);
        if (r.ok) {
          window.addLog(`[Image Manager] Saved crop for "${cropTarget.name}".`);
          // Return to library
          imModal.querySelector(".modal-body").innerHTML = `<div id="im-tabs" class="pos-tabs"></div><div id="im-grid" class="im-grid"></div>`;
          // Re-fetch data to include the new image
          if (window.pywebview && pywebview.api) {
            const fresh = await pywebview.api.list_vision_templates();
            if (fresh.ok) imData = fresh;
          }
          renderImTabs();
          renderImGrid();
        } else {
          window.addLog(`[Image Manager] Save failed: ${r.reason || "error"}`);
        }
      });
    };
    img.src = dataUri;
  }

  // F6 hotkey to open Image Manager (registered in the hotkey loop on the Python side)
  // For now, also accessible via a titlebar button or from Settings.

  // ---- Position Picker Modal ----
  let posTarget = null; // {phase, idx} — which block we're setting coords for
  let posImage = null;  // loaded Image object
  let posCategories = [];
  let posCategory = "";
  let posLastMap = null; // {category, name, dataUri} — remembered across Set clicks

  const posModal = document.getElementById("pos-modal");
  const posTabs = document.getElementById("pos-tabs");
  const posGrid = document.getElementById("pos-grid");
  const posCanvasWrap = document.getElementById("pos-canvas-wrap");
  const posCanvas = document.getElementById("pos-canvas");
  const posReadout = document.getElementById("pos-readout");
  const posCtx = posCanvas.getContext("2d");

  window.openPositionPicker = async function (phase, idx) {
    posTarget = { phase, idx };
    const block = opPhases[phase][idx];
    posReadout.textContent = (block.params?.x && block.params?.y) ? `X ${block.params.x}, Y ${block.params.y}` : "Not set";
    // Hide the game so the modal isn't behind it
    if (window.pywebview && pywebview.api) pywebview.api.set_game_visible(false);
    posModal.style.display = "flex";

    // If we have a recently used map, jump straight to the canvas
    if (posLastMap) {
      loadPosImage(posLastMap.dataUri);
      return;
    }

    // Otherwise show the map grid
    posGrid.style.display = "";
    posCanvasWrap.style.display = "none";
    document.getElementById("pos-back").style.display = "none";

    if (!window.pywebview || !pywebview.api) return;
    posCategories = await pywebview.api.list_map_categories();
    renderPosTabs();
    if (posCategories.length) selectPosCategory(posCategories[0]);
  };

  document.getElementById("pos-close").addEventListener("click", () => {
    posModal.style.display = "none";
    restoreGameIfDashboard();
  });
  document.getElementById("pos-back").addEventListener("click", () => {
    posLastMap = null; // forget the recent map so next Set shows the grid
    posGrid.style.display = "";
    posCanvasWrap.style.display = "none";
    document.getElementById("pos-back").style.display = "none";
  });

  document.getElementById("pos-roblox").addEventListener("click", async () => {
    if (!window.pywebview || !pywebview.api) return;
    const r = await pywebview.api.get_roblox_snapshot();
    if (!r.ok) { window.addLog("Capture failed: " + (r.reason || "error")); return; }
    loadPosImage(r.data_uri);
  });

  function renderPosTabs() {
    posTabs.innerHTML = posCategories.map((c) =>
      `<button class="pos-tab${c === posCategory ? " active" : ""}" data-cat="${c}">${c}</button>`
    ).join("");
    posTabs.querySelectorAll(".pos-tab").forEach((btn) => {
      btn.addEventListener("click", () => selectPosCategory(btn.dataset.cat));
    });
  }

  async function selectPosCategory(cat) {
    posCategory = cat;
    renderPosTabs();
    if (!window.pywebview || !pywebview.api) return;
    const maps = await pywebview.api.list_maps(cat);
    posGrid.innerHTML = maps.map((name) =>
      `<div class="pos-thumb" data-name="${name}"><img alt="${name}"><div class="pos-thumb-label">${name}</div></div>`
    ).join("");
    // Load thumbnails
    posGrid.querySelectorAll(".pos-thumb").forEach((thumb) => {
      const name = thumb.dataset.name;
      pywebview.api.get_map_image(cat, name).then((r) => {
        if (r.ok) thumb.querySelector("img").src = r.data_uri;
      });
      thumb.addEventListener("click", async () => {
        const r = await pywebview.api.get_map_image(cat, name);
        if (r.ok) {
          posLastMap = { category: cat, name, dataUri: r.data_uri };
          loadPosImage(r.data_uri);
        }
      });
    });
  }

  function loadPosImage(dataUri) {
    const img = new Image();
    img.onload = () => {
      posImage = img;
      posLastMap = posLastMap || {};
      posLastMap.dataUri = dataUri;
      posGrid.style.display = "none";
      posCanvasWrap.style.display = "";
      document.getElementById("pos-back").style.display = "";
      fitPosCanvas();
      drawPosCanvas();
    };
    img.src = dataUri;
  }

  let posZoom = 1.0, posPanX = 0, posPanY = 0, posPanning = false, posPanStart = null;

  function fitPosCanvas() {
    if (!posImage) return;
    const wrap = posCanvasWrap;
    const w = wrap.clientWidth || 860;
    const h = wrap.clientHeight || 450;
    const scale = Math.min(w / posImage.naturalWidth, h / posImage.naturalHeight, 1);
    posCanvas.width = w;
    posCanvas.height = h;
    posCanvas.dataset.scale = scale;
    posZoom = 1.0;
    posPanX = (w - posImage.naturalWidth * scale) / 2;
    posPanY = (h - posImage.naturalHeight * scale) / 2;
  }

  function drawPosCanvas() {
    if (!posImage) return;
    const scale = parseFloat(posCanvas.dataset.scale) || 1;
    posCtx.clearRect(0, 0, posCanvas.width, posCanvas.height);
    posCtx.save();
    posCtx.translate(posPanX, posPanY);
    posCtx.scale(posZoom, posZoom);
    posCtx.drawImage(posImage, 0, 0, posImage.naturalWidth * scale, posImage.naturalHeight * scale);

    // Draw ALL blocks with x/y coords as numbered markers
    const COORD_TYPES = ["place_unit", "upgrade_unit", "sell_unit", "target_priority", "click"];
    const TYPE_COLORS = {
      place_unit: "rgba(139, 92, 246, 0.7)",     // purple
      upgrade_unit: "rgba(34, 197, 94, 0.7)",    // teal/green
      sell_unit: "rgba(239, 68, 68, 0.7)",       // rose
      target_priority: "rgba(96, 165, 250, 0.7)", // blue
      click: "rgba(232, 162, 58, 0.7)",          // amber
    };
    let markerNum = 0;
    PHASES.forEach((phase) => {
      (opPhases[phase] || []).forEach((b, idx) => {
        if (!COORD_TYPES.includes(b.type)) return;
        markerNum++;
        const x = (b.params?.x || 0) * scale;
        const y = (b.params?.y || 0) * scale;
        if (!x && !y) return;
        const isCurrent = posTarget && posTarget.phase === phase && posTarget.idx === idx;
        posCtx.beginPath();
        posCtx.arc(x, y, 8 / posZoom, 0, Math.PI * 2);
        posCtx.fillStyle = isCurrent ? "rgba(139, 92, 246, 0.9)" : (TYPE_COLORS[b.type] || "rgba(232, 162, 58, 0.7)");
        posCtx.fill();
        posCtx.strokeStyle = "#fff";
        posCtx.lineWidth = 2 / posZoom;
        posCtx.stroke();
        // Number label
        posCtx.fillStyle = "#fff";
        posCtx.font = `bold ${Math.round(10 / posZoom)}px sans-serif`;
        posCtx.textAlign = "center";
        posCtx.textBaseline = "middle";
        posCtx.fillText(String(markerNum), x, y);
      });
    });
    posCtx.restore();
  }

  // Scroll wheel zoom
  posCanvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = posCanvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const oldZoom = posZoom;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    posZoom = Math.max(0.5, Math.min(5.0, posZoom * factor));
    posPanX = mx - (mx - posPanX) * (posZoom / oldZoom);
    posPanY = my - (my - posPanY) * (posZoom / oldZoom);
    drawPosCanvas();
  }, { passive: false });

  // Middle mouse pan + left click to set position
  posCanvas.addEventListener("mousedown", (e) => {
    if (e.button === 1) {
      e.preventDefault();
      posPanning = true;
      posPanStart = { x: e.clientX - posPanX, y: e.clientY - posPanY };
    }
  });
  posCanvas.addEventListener("mousemove", (e) => {
    if (posPanning && posPanStart) {
      posPanX = e.clientX - posPanStart.x;
      posPanY = e.clientY - posPanStart.y;
      drawPosCanvas();
    }
  });
  posCanvas.addEventListener("mouseup", (e) => {
    if (e.button === 1) posPanning = false;
  });
  posCanvas.addEventListener("contextmenu", (e) => e.preventDefault());

  posCanvas.addEventListener("click", (e) => {
    if (!posTarget || !posImage) return;
    const rect = posCanvas.getBoundingClientRect();
    const scale = parseFloat(posCanvas.dataset.scale) || 1;
    // Convert screen coords to image coords (undo pan + zoom + scale)
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const x = Math.round((sx - posPanX) / posZoom / scale);
    const y = Math.round((sy - posPanY) / posZoom / scale);
    // Write back to the block
    const block = opPhases[posTarget.phase][posTarget.idx];
    block.params = block.params || {};
    block.params.x = x;
    block.params.y = y;
    opDirty = true;
    posReadout.textContent = `X ${x}, Y ${y}`;
    drawPosCanvas();
    renderPhases();
  });

  renderPhases();

  // ---- Walk Path Recording ----
  let walkRecording = false;
  let walkRecPhase = null, walkRecIdx = null;

  async function startWalkRecording(phase, idx) {
    if (!window.pywebview || !pywebview.api) return;
    if (walkRecording) {
      // Stop recording — don't save yet, show name modal
      await pywebview.api.stop_walk_recording();
      walkRecording = false;
      document.getElementById("rec-popout").style.display = "none";
      // Switch back to planner and show name modal
      switchScreen("planner");
      document.getElementById("walk-name-modal").style.display = "flex";
      const input = document.getElementById("walk-name-input");
      input.value = "";
      setTimeout(() => input.focus(), 50);
    } else {
      // Start recording: switch to dashboard
      walkRecPhase = phase;
      walkRecIdx = idx;
      switchScreen("dashboard");
      await new Promise(r => setTimeout(r, 300));
      const name = `walk_${Date.now()}`; // temp name, will be renamed on save
      const r = await pywebview.api.start_walk_recording(name);
      if (r.ok) {
        walkRecording = true;
        document.getElementById("rec-popout").style.display = "flex";
        document.getElementById("rec-popout-text").textContent = "Recording walk path (WASD + Shift)";
        window.addLog("Recording walk path — move in Roblox, then click Stop.");
      } else {
        switchScreen("planner");
      }
    }
  }

  // Walk path name modal handlers
  document.getElementById("walk-name-save").addEventListener("click", async () => {
    const input = document.getElementById("walk-name-input");
    const name = input.value.trim();
    if (!name || !window.pywebview || !pywebview.api) return;
    document.getElementById("walk-name-modal").style.display = "none";
    // Rename the saved walk path to the user's chosen name
    const r = await pywebview.api.rename_walk_path(name);
    if (r.ok) {
      if (walkRecPhase !== null && walkRecIdx !== null) {
        opPhases[walkRecPhase][walkRecIdx].pathName = r.name;
        opDirty = true;
      }
      _cachedWalkPaths = null;
      window.addLog("Walk path saved: " + r.name);
    }
    walkRecPhase = null;
    walkRecIdx = null;
    renderPhases();
  });

  document.getElementById("walk-name-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("walk-name-save").click();
  });

  document.getElementById("walk-name-discard").addEventListener("click", async () => {
    document.getElementById("walk-name-modal").style.display = "none";
    if (window.pywebview && pywebview.api) await pywebview.api.discard_walk_path();
    window.addLog("[Walk] Recording discarded.");
    walkRecPhase = null;
    walkRecIdx = null;
    renderPhases();
  });

  // ---- Recording helpers ----
  let _cachedRecordings = null;
  let _cachedWalkPaths = null;

  window.setWalkPathMode = function(phase, idx, mode) {
    opPhases[phase][idx].mode = mode;
    opDirty = true;
    renderPhases();
  };

  async function populateRecordingSelect(sel, current) {
    if (!window.pywebview || !pywebview.api) return;
    if (!_cachedRecordings) {
      _cachedRecordings = await pywebview.api.list_input_recordings();
    }
    const names = _cachedRecordings || [];
    sel.innerHTML = '<option value="">Select...</option>' + names.map(n =>
      `<option value="${n}"${n === current ? " selected" : ""}>${n}</option>`
    ).join("");
  }

  async function populateWalkPathSelect(sel, current) {
    if (!window.pywebview || !pywebview.api) return;
    if (!_cachedWalkPaths) {
      _cachedWalkPaths = await pywebview.api.list_walk_paths();
    }
    const names = _cachedWalkPaths || [];
    sel.innerHTML = '<option value="">Pick path...</option>' + names.map(n =>
      `<option value="${n}"${n === current ? " selected" : ""}>${n}</option>`
    ).join("");
  }

  async function testRecording(phase, idx) {
    const name = opPhases[phase][idx].recordingName || "";
    if (!name) { window.addLog("[Record] No recording selected to test."); return; }
    if (!window.pywebview || !pywebview.api) return;
    switchScreen("dashboard");
    await new Promise(r => setTimeout(r, 300));
    window.addLog("[Record] Testing: " + name);
    const r = await pywebview.api.test_recording(name);
    if (r.ok) window.addLog("[Record] Replay finished.");
    else window.addLog("[Record] Replay failed: " + (r.reason || "error"));
    switchScreen("planner");
  }

  async function testWalkPath(phase, idx) {
    const name = opPhases[phase][idx].pathName || "";
    if (!name) { window.addLog("[Walk] No path selected to test."); return; }
    if (!window.pywebview || !pywebview.api) return;
    switchScreen("dashboard");
    await new Promise(r => setTimeout(r, 300));
    window.addLog("[Walk] Testing: " + name);
    const r = await pywebview.api.test_walk_path(name);
    if (r.ok) window.addLog("[Walk] Replay finished.");
    else window.addLog("[Walk] Replay failed: " + (r.reason || "error"));
    switchScreen("planner");
  }

  async function deleteRecording(phase, idx) {
    const name = opPhases[phase][idx].recordingName || "";
    if (!name) { window.addLog("[Record] No recording selected to delete."); return; }
    if (!window.pywebview || !pywebview.api) return;
    const r = await pywebview.api.delete_recording(name);
    if (r.ok) {
      opPhases[phase][idx].recordingName = "";
      opDirty = true;
      _cachedRecordings = null;
      window.addLog("[Record] Deleted: " + name);
      renderPhases();
    } else {
      window.addLog("[Record] Delete failed: " + (r.reason || "not found"));
    }
  }

  async function deleteWalkPath(phase, idx) {
    const name = opPhases[phase][idx].pathName || "";
    if (!name) { window.addLog("[Walk] No path selected to delete."); return; }
    if (!window.pywebview || !pywebview.api) return;
    const r = await pywebview.api.delete_walk_path(name);
    if (r.ok) {
      opPhases[phase][idx].pathName = "";
      opDirty = true;
      _cachedWalkPaths = null;
      window.addLog("[Walk] Deleted: " + name);
      renderPhases();
    } else {
      window.addLog("[Walk] Delete failed: not found");
    }
  }

  // ---- Input Recording (Record block) ----
  let inputRecording = false;
  let recordingBlockPhase = null;
  let recordingBlockIdx = null;

  async function startInputRecording(phase, idx) {
    if (!window.pywebview || !pywebview.api) return;

    if (inputRecording) {
      // Stop recording
      document.getElementById("rec-popout").style.display = "none";
      const result = await pywebview.api.stop_input_recording();
      inputRecording = false;

      if (!result.ok || !result.count) {
        window.addLog("[Record] Nothing captured — no input detected.");
        await pywebview.api.discard_pending_recording();
        recordingBlockPhase = null;
        recordingBlockIdx = null;
        // Switch back to planner
        switchScreen("planner");
        renderPhases();
        return;
      }

      // Switch back to planner and show name modal
      switchScreen("planner");
      document.getElementById("rec-name-modal").style.display = "flex";
      const input = document.getElementById("rec-name-input");
      input.value = "";
      setTimeout(() => input.focus(), 50);
      return;
    }

    // Start recording: switch to dashboard so game is visible
    recordingBlockPhase = phase;
    recordingBlockIdx = idx;
    switchScreen("dashboard");
    await new Promise(r => setTimeout(r, 300)); // let game become visible

    const r = await pywebview.api.start_input_recording();
    if (r.ok) {
      inputRecording = true;
      document.getElementById("rec-popout").style.display = "flex";
      window.addLog("[Record] Recording input — act inside Roblox, then click Stop.");
    } else {
      window.addLog("[Record] Couldn't start: " + (r.reason || "error"));
      switchScreen("planner");
    }
  }

  // Stop button in the recording popout (handles both input recording and walk recording)
  document.getElementById("rec-stop-btn").addEventListener("click", () => {
    if (inputRecording && recordingBlockPhase !== null) {
      startInputRecording(recordingBlockPhase, recordingBlockIdx);
    } else if (walkRecording && walkRecPhase !== null) {
      startWalkRecording(walkRecPhase, walkRecIdx);
    }
  });

  // Save recording name modal
  document.getElementById("rec-name-save").addEventListener("click", async () => {
    const input = document.getElementById("rec-name-input");
    const name = input.value.trim();
    if (!name || !window.pywebview || !pywebview.api) return;
    document.getElementById("rec-name-modal").style.display = "none";
    const result = await pywebview.api.save_pending_recording(name);
    if (result.ok) {
      _cachedRecordings = null; // refresh dropdown list
      // Wire the name back to the block
      if (recordingBlockPhase !== null && recordingBlockIdx !== null) {
        opPhases[recordingBlockPhase][recordingBlockIdx].recordingName = result.name;
        opDirty = true;
      }
      window.addLog("[Record] Saved: " + result.name);
    } else {
      window.addLog("[Record] Save failed: " + (result.reason || "error"));
    }
    recordingBlockPhase = null;
    recordingBlockIdx = null;
    renderPhases();
  });

  // Enter key in the name input
  document.getElementById("rec-name-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("rec-name-save").click();
  });

  // Discard / close
  document.getElementById("rec-name-discard").addEventListener("click", async () => {
    document.getElementById("rec-name-modal").style.display = "none";
    if (window.pywebview && pywebview.api) await pywebview.api.discard_pending_recording();
    window.addLog("[Record] Recording discarded.");
    recordingBlockPhase = null;
    recordingBlockIdx = null;
    renderPhases();
  });
  document.getElementById("rec-name-cancel").addEventListener("click", () => {
    document.getElementById("rec-name-discard").click();
  });
})();
