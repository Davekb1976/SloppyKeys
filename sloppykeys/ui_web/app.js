// SloppyKeys — UI controller
// Screen switching, nav state, placeholder bridge hooks.

(function () {
  "use strict";

  // ---- Navigation ----
  const navButtons = document.querySelectorAll(".nav-btn[data-screen]");
  const screens = document.querySelectorAll(".screen");

  function switchScreen(name) {
    screens.forEach((el) => el.classList.toggle("active", el.id === "screen-" + name));
    navButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.screen === name));
  }

  navButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchScreen(btn.dataset.screen));
  });

  // ---- Window controls (wired when pywebview bridge is ready) ----
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
    div.className = "log-entry";
    div.textContent = "> " + line;
    logList.appendChild(div);
    while (logList.childElementCount > LOG_MAX) logList.removeChild(logList.firstElementChild);
    logList.scrollTop = logList.scrollHeight;
  };

  document.getElementById("btn-clear-log").addEventListener("click", () => {
    logList.innerHTML = "";
  });

  // ---- Uptime ----
  const uptimeEl = document.getElementById("uptime");
  const startTime = Date.now();

  function tickUptime() {
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    const h = String(Math.floor(elapsed / 3600)).padStart(2, "0");
    const m = String(Math.floor((elapsed % 3600) / 60)).padStart(2, "0");
    const s = String(elapsed % 60).padStart(2, "0");
    uptimeEl.textContent = h + ":" + m + ":" + s;
  }
  setInterval(tickUptime, 1000);
  tickUptime();
})();
