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

  btnStart.addEventListener("click", () => {
    if (!window.pywebview || !pywebview.api) return;
    // Start runs the task queue — no selector needed.
    pywebview.api.start_macro("", "", "", "").then((r) => {
      if (!r.ok) window.addLog("Start blocked: " + r.error);
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
    loadMaps(task.mode, task.map);
    loadStages(task.mode, task.map, task.stage);
    tbDifficulty.value = task.difficulty || "Normal";
    tbRepeat.value = task.repeat || 1;
    tbMacro.value = task.macro || "";
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
    pywebview.api.update_task(selectedTaskId, changes).then(() => {
      const t = tasks.find((x) => x.id === selectedTaskId);
      if (t) Object.assign(t, changes);
      renderTaskList();
    });
  }

  // Cascade: mode → maps, map → stages
  tbMode.addEventListener("change", () => {
    loadMaps(tbMode.value, "");
    tbStage.innerHTML = '<option value="">—</option>';
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

  document.getElementById("btn-remove-task").addEventListener("click", () => {
    if (!selectedTaskId || !window.pywebview || !pywebview.api) return;
    pywebview.api.remove_task(selectedTaskId).then(() => {
      tasks = tasks.filter((t) => t.id !== selectedTaskId);
      selectedTaskId = null;
      renderTaskList();
      showBuilderEmpty();
    });
  });

  // Populate gamemodes in the task builder mode dropdown + load queue
  window.addEventListener("pywebviewready", () => {
    loadTasks();
    if (window.pywebview && pywebview.api && pywebview.api.get_gamemodes) {
      pywebview.api.get_gamemodes().then((modes) => {
        tbMode.innerHTML = modes.map((m) => `<option value="${m}">${m}</option>`).join("");
      });
    }
    loadOperationList();
  });

  // Called from Python's on_loaded after _app_root is set.
  window.onBackendReady = function () {
    loadSettings();
  };

  // ---- Macro Manager ----
  const PHASES = ["pre_start", "battle", "loop_a", "loop_b"];
  let opPhases = { pre_start: [], battle: [], loop_a: [], loop_b: [] };
  let opDirty = false;

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
        let fields = "";
        if (b.type === "place_unit") fields = `<input placeholder="name" value="${b.params?.name || ""}" data-field="params.name"><input placeholder="x" value="${b.params?.x || 0}" data-field="params.x" type="number"><input placeholder="y" value="${b.params?.y || 0}" data-field="params.y" type="number"><button class="btn btn--sm" onclick="openPositionPicker('${phase}',${i})">Set</button>`;
        else if (b.type === "wait_ms") fields = `<input placeholder="ms" value="${b.params?.ms || 500}" data-field="params.ms" type="number">`;
        else if (b.type === "wait_wave") fields = `<input placeholder="wave" value="${b.params?.wave || 1}" data-field="params.wave" type="number">`;
        else if (b.type === "leave_at_minute") fields = `<input placeholder="min" value="${b.params?.minutes || 10}" data-field="params.minutes" type="number">`;
        else if (b.type === "click") fields = `<input placeholder="x" value="${b.params?.x || 0}" data-field="params.x" type="number"><input placeholder="y" value="${b.params?.y || 0}" data-field="params.y" type="number"><button class="btn btn--sm" onclick="openPositionPicker('${phase}',${i})">Set</button>`;
        else if (b.type === "send_key") fields = `<input placeholder="key" value="${b.key || ""}" data-field="key" style="width:40px;"><input placeholder="hold ms" value="${b.params?.hold_ms || 0}" data-field="params.hold_ms" type="number">`;
        else if (b.type === "upgrade_unit" || b.type === "sell_unit" || b.type === "target_priority") fields = `<input placeholder="#" value="${b.params?.index || 1}" data-field="params.index" type="number" style="width:40px;">`;
        return `<div class="block-row" data-phase="${phase}" data-idx="${i}">
          <span class="block-type">${b.type.replace(/_/g, " ")}</span>
          <span class="block-fields">${fields}</span>
          <span class="block-remove" data-phase="${phase}" data-idx="${i}">&times;</span>
        </div>`;
      }).join("");

      // Wire inline field edits
      zone.querySelectorAll("input[data-field]").forEach((inp) => {
        inp.addEventListener("change", (e) => {
          const row = e.target.closest(".block-row");
          const ph = row.dataset.phase;
          const idx = parseInt(row.dataset.idx);
          const field = e.target.dataset.field;
          const val = e.target.type === "number" ? Number(e.target.value) : e.target.value;
          if (field.startsWith("params.")) {
            const key = field.split(".")[1];
            opPhases[ph][idx].params = opPhases[ph][idx].params || {};
            opPhases[ph][idx].params[key] = val;
          } else {
            opPhases[ph][idx][field] = val;
          }
          opDirty = true;
        });
      });

      // Wire remove buttons
      zone.querySelectorAll(".block-remove").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const ph = btn.dataset.phase;
          const idx = parseInt(btn.dataset.idx);
          opPhases[ph].splice(idx, 1);
          opDirty = true;
          renderPhases();
        });
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
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag-over"); });
    zone.addEventListener("dragleave", () => { zone.classList.remove("drag-over"); });
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("drag-over");
      const type = e.dataTransfer.getData("text/plain");
      if (!type) return;
      const block = { type, params: {} };
      if (type === "place_unit") block.params = { name: "", x: 0, y: 0 };
      else if (type === "wait_ms") block.params = { ms: 500 };
      else if (type === "wait_wave") block.params = { wave: 1 };
      else if (type === "leave_at_minute") block.params = { minutes: 10 };
      else if (type === "click") block.params = { x: 0, y: 0 };
      else if (type === "send_key") { block.key = ""; block.params = { hold_ms: 0 }; }
      else if (type === "upgrade_unit" || type === "sell_unit" || type === "target_priority") block.params = { index: 1 };
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
    opPhases = { pre_start: [], battle: [], loop_a: [], loop_b: [] };
    opDirty = false;
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

  wireAutoSave();

  // ---- Image Manager Modal ----
  let imData = null;
  let imCategory = "all";
  const imModal = document.getElementById("im-modal");
  const imGrid = document.getElementById("im-grid");
  const imTabs = document.getElementById("im-tabs");
  const imFilter = document.getElementById("im-filter");

  window.openImageManager = async function () {
    imModal.style.display = "flex";
    if (!window.pywebview || !pywebview.api) return;
    const result = await pywebview.api.list_vision_templates();
    if (!result.ok) return;
    imData = result;
    renderImTabs();
    renderImGrid();
  };

  document.getElementById("im-close").addEventListener("click", () => { imModal.style.display = "none"; });
  document.getElementById("im-capture").addEventListener("click", async () => {
    if (!window.pywebview || !pywebview.api) return;
    const r = await pywebview.api.get_roblox_snapshot();
    if (r.ok) window.addLog("[Image Manager] Captured Roblox screen.");
    else window.addLog("[Image Manager] Capture failed: " + (r.reason || "error"));
  });

  imFilter.addEventListener("input", () => renderImGrid());

  function renderImTabs() {
    if (!imData) return;
    const cats = [{ key: "all", label: "All" }].concat(imData.categories.map((c) => ({ key: c.key, label: c.label })));
    imTabs.innerHTML = cats.map((c) =>
      `<button class="pos-tab${c.key === imCategory ? " active" : ""}" data-cat="${c.key}">${c.label}</button>`
    ).join("");
    imTabs.querySelectorAll(".pos-tab").forEach((btn) => {
      btn.addEventListener("click", () => { imCategory = btn.dataset.cat; renderImTabs(); renderImGrid(); });
    });
  }

  function renderImGrid() {
    if (!imData) { imGrid.innerHTML = ""; return; }
    const q = (imFilter.value || "").trim().toLowerCase();
    let items = [];
    imData.categories.forEach((cat) => {
      if (imCategory !== "all" && cat.key !== imCategory) return;
      cat.names.forEach((img) => {
        if (q && !img.name.toLowerCase().includes(q)) return;
        items.push({ ...img, catKey: cat.key, catLabel: cat.label });
      });
    });
    imGrid.innerHTML = items.map((img) => `
      <div class="im-card">
        <div class="im-card-header">
          <span class="im-card-cat">${img.catKey}</span>
          <span class="im-card-name">${img.name}</span>
        </div>
        <img class="im-card-thumb" src="${img.data_uri}" alt="${img.name}">
        <div class="im-card-slider">
          <span>Match</span>
          <input type="range" min="0.50" max="1.00" step="0.01" value="${img.threshold}" data-name="${img.name}">
          <span class="im-val">${img.threshold.toFixed(2)}</span>
        </div>
      </div>
    `).join("");
    // Wire sliders
    imGrid.querySelectorAll('input[type="range"]').forEach((slider) => {
      slider.addEventListener("input", (e) => {
        e.target.closest(".im-card-slider").querySelector(".im-val").textContent = parseFloat(e.target.value).toFixed(2);
      });
      slider.addEventListener("change", (e) => {
        if (!window.pywebview || !pywebview.api) return;
        pywebview.api.set_image_threshold(e.target.dataset.name, parseFloat(e.target.value));
      });
    });
  }

  // F6 hotkey to open Image Manager (registered in the hotkey loop on the Python side)
  // For now, also accessible via a titlebar button or from Settings.

  // ---- Position Picker Modal ----
  let posTarget = null; // {phase, idx} — which block we're setting coords for
  let posImage = null;  // loaded Image object
  let posCategories = [];
  let posCategory = "";

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
    posModal.style.display = "flex";
    posGrid.style.display = "";
    posCanvasWrap.style.display = "none";
    document.getElementById("pos-back").style.display = "none";

    if (!window.pywebview || !pywebview.api) return;
    posCategories = await pywebview.api.list_map_categories();
    renderPosTabs();
    if (posCategories.length) selectPosCategory(posCategories[0]);
  };

  document.getElementById("pos-close").addEventListener("click", () => { posModal.style.display = "none"; });
  document.getElementById("pos-back").addEventListener("click", () => {
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
        if (r.ok) loadPosImage(r.data_uri);
      });
    });
  }

  function loadPosImage(dataUri) {
    const img = new Image();
    img.onload = () => {
      posImage = img;
      posGrid.style.display = "none";
      posCanvasWrap.style.display = "";
      document.getElementById("pos-back").style.display = "";
      fitPosCanvas();
      drawPosCanvas();
    };
    img.src = dataUri;
  }

  function fitPosCanvas() {
    if (!posImage) return;
    const wrap = posCanvasWrap;
    const w = wrap.clientWidth || 860;
    const h = wrap.clientHeight || 560;
    const scale = Math.min(w / posImage.naturalWidth, h / posImage.naturalHeight, 1);
    posCanvas.width = Math.floor(posImage.naturalWidth * scale);
    posCanvas.height = Math.floor(posImage.naturalHeight * scale);
    posCanvas.dataset.scale = scale;
  }

  function drawPosCanvas() {
    if (!posImage) return;
    const scale = parseFloat(posCanvas.dataset.scale) || 1;
    posCtx.clearRect(0, 0, posCanvas.width, posCanvas.height);
    posCtx.drawImage(posImage, 0, 0, posCanvas.width, posCanvas.height);
    // Draw existing mark
    if (posTarget) {
      const block = opPhases[posTarget.phase][posTarget.idx];
      const x = (block.params?.x || 0) * scale;
      const y = (block.params?.y || 0) * scale;
      if (x || y) {
        posCtx.beginPath();
        posCtx.arc(x, y, 6, 0, Math.PI * 2);
        posCtx.fillStyle = "rgba(139, 92, 246, 0.7)";
        posCtx.fill();
        posCtx.strokeStyle = "#fff";
        posCtx.lineWidth = 2;
        posCtx.stroke();
      }
    }
  }

  posCanvas.addEventListener("click", (e) => {
    if (!posTarget || !posImage) return;
    const rect = posCanvas.getBoundingClientRect();
    const scale = parseFloat(posCanvas.dataset.scale) || 1;
    const x = Math.round((e.clientX - rect.left) / scale);
    const y = Math.round((e.clientY - rect.top) / scale);
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
})();
