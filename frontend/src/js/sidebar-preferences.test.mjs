import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const template = fs.readFileSync(
  new URL("../../templates/base_app.html", import.meta.url),
  "utf8",
);

function inlineScript(attribute) {
  const match = template.match(new RegExp(`<script ${attribute}>([\\s\\S]*?)<\\/script>`));
  assert.ok(match, `Missing ${attribute} script`);
  return match[1];
}

test("saved sidebar size and collapsed state are applied before Alpine loads", () => {
  const classes = new Set();
  const styles = new Map();
  const storage = new Map([
    ["rowsetSidebarCollapsed", "true"],
    ["rowsetSidebarDisclosures", JSON.stringify({ "project:alpha": false })],
    ["rowsetSidebarWidth", "376"],
  ]);
  const context = vm.createContext({
    Array,
    JSON,
    Number,
    Object,
    document: {
      documentElement: {
        classList: {
          toggle(name, enabled) {
            if (enabled) classes.add(name);
            else classes.delete(name);
          },
        },
        style: {
          setProperty(name, value) {
            styles.set(name, value);
          },
        },
      },
    },
    localStorage: {
      getItem(key) {
        return storage.get(key) ?? null;
      },
    },
    window: { matchMedia: () => ({ matches: false }) },
  });

  vm.runInContext(inlineScript("data-sidebar-preferences-bootstrap"), context);

  assert.equal(styles.get("--app-sidebar-width"), "64px");
  assert.equal(classes.has("rowset-sidebar-collapsed"), true);
  assert.equal(context.window.Rowset.sidebarPreferences.width, 376);
  assert.equal(context.window.Rowset.sidebarPreferences.disclosures["project:alpha"], false);
});

test("saved project and section states are applied while the sidebar markup is parsed", () => {
  const elements = [
    { dataset: { sidebarDisclosureKey: "project:alpha" }, open: true },
    { dataset: { sidebarDisclosureKey: "section:sales" }, open: false },
    { dataset: { sidebarDisclosureKey: "section:unsaved" }, open: true },
  ];
  const sidebar = { querySelectorAll: () => elements };
  const context = vm.createContext({
    Object,
    document: { currentScript: { parentElement: sidebar } },
    window: {
      Rowset: {
        sidebarPreferences: {
          disclosures: { "project:alpha": false, "section:sales": true },
        },
      },
    },
  });

  vm.runInContext(inlineScript("data-sidebar-disclosures-bootstrap"), context);

  assert.deepEqual(elements.map((element) => element.open), [false, true, true]);
});
