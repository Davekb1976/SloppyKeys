// Every <button id="..."> in index.html must be reachable from app.js.
//
//     node tests\test_ui_buttons_wired.js
//
// "Clone Task did nothing" was a button that shipped with no handler at all: the markup was
// there, the id was there, and no line of JS ever mentioned it. Nothing caught it —
// `node --check` parses, and the load harness stubs `getElementById` with a Proxy that
// answers to any id, so a button nobody wired looks identical to one that works.
//
// Checked against the *source text*, not a DOM: the failure is an absent reference, which is
// visible without rendering anything. A button is considered wired if app.js mentions its id
// (as a string or a `#id` selector) or if the tag carries its own inline `onclick`.
//
// Delegated handlers are the reason this is a text search rather than a strict rule: a button
// driven by its class or a data attribute still has to be named somewhere for this to pass,
// which is true of every one in the file today. If a genuinely delegated button ever trips
// this, reference its id in a comment beside the delegation rather than widening the check.

const fs = require("fs");
const path = require("path");

const dir = path.join(__dirname, "..", "sloppykeys", "ui_web");
const html = fs.readFileSync(path.join(dir, "index.html"), "utf8");
const js = fs.readFileSync(path.join(dir, "app.js"), "utf8");

const tags = html.match(/<button\b[^>]*>/g) || [];
const withId = tags.filter((tag) => /\bid="/.test(tag));
const unwired = [];

for (const tag of tags) {
  const id = (tag.match(/\bid="([^"]+)"/) || [])[1];
  if (!id) continue;                      // styled by class, handled by delegation
  if (tag.includes("onclick")) continue;  // handler is inline in the markup
  if (js.includes(`"${id}"`) || js.includes(`'${id}'`) || js.includes(`#${id}`)) continue;
  unwired.push(id);
}

if (tags.length === 0 || withId.length === 0) {
  console.error("FAIL: parsed no buttons out of index.html — the regex or the markup moved");
  process.exit(1);
}

if (unwired.length > 0) {
  console.error(
    `FAIL: ${unwired.length} button(s) in index.html are referenced nowhere in app.js, ` +
      `so clicking them does nothing:`
  );
  for (const id of unwired) console.error(`  #${id}`);
  process.exit(1);
}

console.log(`OK: all ${withId.length} identified buttons are referenced in app.js`);
