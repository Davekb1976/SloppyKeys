// Test that openPositionPicker and canvas click correctly set coordinates
// on nested blocks inside detect branches, rather than mutating the parent detect block.
//
//     node tests\test_nested_block_coords.js

const fs = require("fs");
const path = require("path");
const vm = require("vm");

let loadedPhases = null;
const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) {
    let text = "";
    const listeners = {};
    elements.set(id, {
      id,
      style: {},
      get textContent() { return text; },
      set textContent(v) { text = v; },
      addEventListener(evt, fn) { (listeners[evt] = listeners[evt] || []).push(fn); },
      dispatchEvent(evt, data = {}) { return Promise.all((listeners[evt] || []).map(fn => fn(Object.assign({ target: this }, data)))); },
      querySelectorAll: () => [],
      querySelector: () => getEl("child"),
      closest: () => getEl("parent"),
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 600 }),
      getContext: () => ({
        clearRect() {}, save() {}, restore() {}, translate() {}, scale() {},
        drawImage() {}, beginPath() {}, arc() {}, fill() {}, stroke() {}, fillText() {},
      }),
      classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
      dataset: { scale: "1" },
      value: "",
    });
  }
  return elements.get(id);
}

const sandbox = {
  console,
  setTimeout,
  setInterval: () => 0,
  clearInterval: () => {},
  requestAnimationFrame: () => 0,
  Image: function () {
    const img = getEl("img");
    img.naturalWidth = 1152;
    img.naturalHeight = 756;
    let _src = "";
    Object.defineProperty(img, "src", {
      set(v) { _src = v; if (img.onload) img.onload(); },
      get() { return _src; },
    });
    return img;
  },
  addEventListener: () => {},
  document: {
    getElementById: (id) => getEl(id),
    querySelector: (sel) => getEl(sel),
    querySelectorAll: () => [],
    createElement: () => getEl("elem"),
    addEventListener: () => {},
    body: getEl("body"),
  },
  pywebview: {
    api: {
      load_operation: async () => {
        loadedPhases = {
          pre_start: [{ type: "walk_path" }],
          battle: [{
            type: "detect",
            params: {},
            then: [{ type: "click", params: { x: 0, y: 0 } }],
            else: [],
          }],
          loop_a: [],
          loop_b: [],
        };
        return { name: "test", phases: loadedPhases };
      },
      list_operations: async () => [],
      list_map_categories: async () => [],
      list_maps: async () => [],
      get_roblox_snapshot: async () => ({ ok: true, data_uri: "data:image/png;base64,xyz" }),
    },
  },
};
sandbox.window = sandbox;

const appJs = path.join(__dirname, "..", "sloppykeys", "ui_web", "app.js");
vm.runInNewContext(fs.readFileSync(appJs, "utf8"), sandbox, { filename: "app.js" });

(async () => {
  const opLoad = getEl("op-load");
  opLoad.value = "test";
  await opLoad.dispatchEvent("change");

  // Open position picker for nested click block in Then branch
  await sandbox.window.openPositionPicker("battle", 0, 0, "then");
  const posRoblox = getEl("pos-roblox");
  await posRoblox.dispatchEvent("click");

  // Click on canvas
  const canvas = getEl("pos-canvas");
  await canvas.dispatchEvent("click", { clientX: 320, clientY: 240 });

  if (loadedPhases.battle[0].then[0].params.x === 0 && loadedPhases.battle[0].then[0].params.y === 0) {
    console.error("FAIL: Nested click coords were not updated!");
    process.exit(1);
  }
  if (loadedPhases.battle[0].params.x || loadedPhases.battle[0].params.y) {
    console.error("FAIL: Outer detect params were incorrectly modified!");
    process.exit(1);
  }
  console.log("OK: nested block position picker sets coords correctly");
})();
