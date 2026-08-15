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

  // Populate gamemodes in the task builder mode dropdown
  window.addEventListener("pywebviewready", () => {
    loadGamemodes();
    loadTasks();
    if (pywebview.api.get_gamemodes) {
      pywebview.api.get_gamemodes().then((modes) => {
        tbMode.innerHTML = modes.map((m) => `<option value="${m}">${m}</option>`).join("");
      });
    }
  });
})();
