// Does app.js run top to bottom without throwing?
//
//     node tests\test_app_js_loads.js
//
// The one thing `node --check` cannot tell you. A throw from a top-level statement aborts
// the rest of the file, so every listener declared after it is never wired — and WebView2
// has no console, so the page just sits there half dead. That is how a `let` declared below
// its first use (temporal dead zone) took out the whole Macro Manager: drag a block, no
// block; pick an operation, no load.
//
// The DOM is a Proxy that answers everything with another Proxy, which is enough for the
// registration pass. Nothing here renders or asserts on markup — a real DOM would be a
// browser, and the failure being guarded against happens before any of that matters.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

function stub() {
  return new Proxy(function () {}, {
    get(_t, k) {
      if (k === "classList") return { toggle() {}, add() {}, remove() {}, contains: () => false };
      if (k === "dataset") return {};
      if (k === "style") return {};
      if (k === "length" || k === "childElementCount" || k === "scrollHeight") return 0;
      if (k === "forEach" || k === "map" || k === "filter") return () => [];
      if (k === "querySelectorAll") return () => [];
      if (k === "textContent" || k === "innerHTML" || k === "value") return "";
      if (k === Symbol.toPrimitive) return () => "";
      return stub();
    },
    set() { return true; },
    apply() { return stub(); },
  });
}

const sandbox = {
  console,
  setTimeout,
  setInterval: () => 0,
  clearInterval: () => {},
  requestAnimationFrame: () => 0,
  Image: function () { return stub(); },
  addEventListener: () => {},
  document: {
    getElementById: () => stub(),
    querySelector: () => stub(),
    querySelectorAll: () => [],
    createElement: () => stub(),
    addEventListener: () => {},
    body: stub(),
  },
};
sandbox.window = sandbox;

const appJs = path.join(__dirname, "..", "sloppykeys", "ui_web", "app.js");
try {
  vm.runInNewContext(fs.readFileSync(appJs, "utf8"), sandbox, { filename: "app.js" });
} catch (e) {
  console.error(`app.js threw at load: ${e.name}: ${e.message}`);
  console.error((e.stack || "").split("\n").slice(1, 3).join("\n"));
  process.exit(1);
}
console.log("OK: app.js ran to the end");
