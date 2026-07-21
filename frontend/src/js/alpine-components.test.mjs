import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./alpine-components.js", import.meta.url), "utf8");

function loadAlpineComponents({ storedValues = {} } = {}) {
  const components = new Map();
  const eventListeners = new Map();
  const storage = new Map(Object.entries(storedValues));
  const storageWrites = [];
  const timers = new Map();
  let nextTimerId = 1;
  let initializeAlpine;
  const window = {
    addEventListener(name, callback) {
      eventListeners.set(name, callback);
    },
    clearTimeout(timerId) {
      timers.delete(timerId);
    },
    matchMedia() {
      return { matches: false };
    },
    removeEventListener(name) {
      eventListeners.delete(name);
    },
    setTimeout(callback) {
      const timerId = nextTimerId;
      nextTimerId += 1;
      timers.set(timerId, callback);
      return timerId;
    },
  };
  const localStorage = {
    getItem(key) {
      return storage.get(key) ?? null;
    },
    setItem(key, value) {
      storage.set(key, String(value));
      storageWrites.push([key, String(value)]);
    },
  };
  const context = vm.createContext({
    AbortController: globalThis.AbortController,
    Alpine: {
      data(name, factory) {
        components.set(name, factory);
      },
    },
    CustomEvent,
    document: {
      addEventListener(name, callback) {
        if (name === "alpine:init") {
          initializeAlpine = callback;
        }
      },
      body: {
        classList: { add() {}, remove() {} },
      },
      documentElement: {
        classList: { toggle() {} },
      },
    },
    fetch: async () => ({ ok: true, text: async () => "# Markdown" }),
    navigator: {},
    localStorage,
    window,
  });

  vm.runInContext(source, context);
  initializeAlpine();

  return {
    components,
    context,
    eventListeners,
    rowset: context.window.Rowset,
    storage,
    storageWrites,
    timers,
    window,
  };
}

function loadAppShell(storedValues = {}) {
  const loaded = loadAlpineComponents({ storedValues });
  return { ...loaded, component: loaded.components.get("appShell")() };
}

function loadCopyPanel() {
  const loaded = loadAlpineComponents();
  return { ...loaded, component: loaded.components.get("copyPanel")() };
}

function loadAiReaderMenu() {
  const loaded = loadAlpineComponents();
  const component = loaded.components.get("aiReaderMenu")();
  component.$el = {
    dataset: {
      markdownUrl: "https://rowset.example/docs/quickstart.md",
      prompt: "Read this Rowset page",
    },
  };
  return { ...loaded, component };
}

function loadChoiceFilter(checkedValues = []) {
  const loaded = loadAlpineComponents();
  const component = loaded.components.get("choiceFilter")();
  component.$root = {
    querySelectorAll(selector) {
      assert.equal(selector, "input[type='checkbox']:checked");
      return checkedValues.map((value) => ({ value }));
    },
  };
  component.$refs = { trigger: { focus() {} } };
  return { ...loaded, component };
}

test("app shell restores sidebar size, visibility, and disclosure preferences", () => {
  const { component } = loadAppShell({
    rowsetSidebarCollapsed: "true",
    rowsetSidebarDisclosures: JSON.stringify({
      "project:alpha": false,
      "section:sales": true,
    }),
    rowsetSidebarWidth: "376",
  });
  const project = {
    dataset: { sidebarDisclosureKey: "project:alpha" },
    open: true,
  };
  const section = {
    dataset: { sidebarDisclosureKey: "section:sales" },
    open: false,
  };

  component.init();
  component.syncSidebarDisclosure(project);
  component.syncSidebarDisclosure(section);

  assert.equal(component.sidebarCollapsed, true);
  assert.equal(component.sidebarWidth, 376);
  assert.equal(project.open, false);
  assert.equal(section.open, true);
});

test("app shell restores an unsaved disclosure after temporary search expansion", () => {
  const { component, storageWrites } = loadAppShell();
  const project = {
    dataset: { sidebarDisclosureKey: "project:alpha" },
    open: false,
  };

  component.init();
  component.syncSidebarDisclosure(project);
  component.sidebarQuery = "alpha";
  component.syncSidebarDisclosure(project);

  assert.equal(project.open, true);

  component.sidebarQuery = "";
  component.syncSidebarDisclosure(project);

  assert.equal(project.open, false);
  assert.deepEqual(storageWrites, []);
});

test("app shell ignores malformed or non-boolean disclosure preferences", () => {
  const malformed = loadAppShell({ rowsetSidebarDisclosures: "{" }).component;
  const invalidValues = loadAppShell({
    rowsetSidebarDisclosures: JSON.stringify({
      "project:alpha": "false",
      "section:sales": true,
    }),
  }).component;

  malformed.init();
  invalidValues.init();

  assert.deepEqual(Object.keys(malformed.sidebarDisclosures), []);
  assert.deepEqual(Object.keys(invalidValues.sidebarDisclosures), ["section:sales"]);
});

test("app shell persists sidebar interactions and ignores non-user disclosure changes", () => {
  const { component, eventListeners, storage, storageWrites } = loadAppShell({
    rowsetSidebarDisclosures: JSON.stringify({ "project:alpha": false }),
  });
  const project = {
    dataset: { sidebarDisclosureKey: "project:alpha" },
    open: false,
  };

  component.init();
  component.startSidebarResize({ preventDefault() {} });
  eventListeners.get("pointermove")({ clientX: 392 });
  eventListeners.get("pointerup")();
  component.toggleSidebar();
  project.open = true;
  component.rememberSidebarDisclosure({ currentTarget: project });

  assert.equal(storage.get("rowsetSidebarCollapsed"), "true");
  assert.equal(storage.get("rowsetSidebarWidth"), "392");
  assert.deepEqual(JSON.parse(storage.get("rowsetSidebarDisclosures")), {
    "project:alpha": true,
  });

  const writesAfterUserInteractions = storageWrites.length;
  component.rememberSidebarDisclosure({ currentTarget: project });

  assert.equal(storageWrites.length, writesAfterUserInteractions);

  component.sidebarQuery = "alpha";
  project.open = false;
  component.rememberSidebarDisclosure({ currentTarget: project });

  assert.deepEqual(JSON.parse(storage.get("rowsetSidebarDisclosures")), {
    "project:alpha": true,
  });
});

test("choice filter summarizes and clears multiple checked choices", () => {
  const { component } = loadChoiceFilter(["P1", "P2"]);

  component.init();

  assert.deepEqual(Array.from(component.selected), ["P1", "P2"]);
  assert.equal(component.summary(), "2 choices selected");

  component.clear();

  assert.deepEqual(Array.from(component.selected), []);
  assert.equal(component.summary(), "Any choice");
});

async function runCopy({ copied }) {
  const { component, rowset } = loadCopyPanel();
  const dispatched = [];
  const parent = new EventTarget();
  const element = new EventTarget();
  element.dataset = { copySuccessEvent: "agent-setup-prompt-copied" };
  const dispatchOnElement = element.dispatchEvent.bind(element);
  element.dispatchEvent = (event) => {
    const result = dispatchOnElement(event);
    if (event.bubbles) {
      parent.dispatchEvent(event);
    }
    return result;
  };
  parent.addEventListener("agent-setup-prompt-copied", (event) => dispatched.push(event));
  component.$el = element;
  component.$refs = {};
  component.copyText = async () => "setup prompt";
  component.flashLabel = () => {};
  rowset.copyTextToClipboard = async () => copied;

  await component.copy({ preventDefault() {} });

  return { component, dispatched };
}

test("successful clipboard copy dispatches prompt completion", async () => {
  const { component, dispatched } = await runCopy({ copied: true });

  assert.equal(dispatched.length, 1);
  assert.equal(dispatched[0].type, "agent-setup-prompt-copied");
  assert.equal(dispatched[0].bubbles, true);
  assert.equal(dispatched[0].composed, false);
  assert.equal(dispatched[0].cancelable, false);
  assert.equal(component.busy, false);
});

test("failed clipboard copy leaves prompt task incomplete", async () => {
  const { component, dispatched } = await runCopy({ copied: false });

  assert.deepEqual(dispatched, []);
  assert.equal(component.busy, false);
});

test("copy panel copies the full prompt from its protected JSON endpoint", async () => {
  const { component, context, rowset } = loadCopyPanel();
  const copiedValues = [];
  rowset.posthogSessionHeaders = () => ({});
  rowset.copyTextToClipboard = async (value) => {
    copiedValues.push(value);
    return true;
  };
  const panelElement = new EventTarget();
  panelElement.dataset = {
    copyUrl: "/home/agent-setup-prompt/",
    copyResponseKey: "prompt",
    copyLabel: "Copy setup prompt",
  };
  const buttonElement = {
    dataset: {},
    closest(selector) {
      assert.equal(selector, "[data-copy-url], [data-copy-label]");
      return panelElement;
    },
  };
  component.$el = buttonElement;
  component.$refs = {
    source: { textContent: "Rowset API key: ***" },
  };
  component.flashLabel = () => {};
  context.fetch = async (url, options) => {
    assert.equal(url, "/home/agent-setup-prompt/");
    assert.equal(options.credentials, "same-origin");
    return {
      ok: true,
      json: async () => ({ prompt: "Rowset API key: rsk_full_secret" }),
    };
  };

  await component.copy({ preventDefault() {}, currentTarget: buttonElement });

  assert.deepEqual(copiedValues, ["Rowset API key: rsk_full_secret"]);
  assert.equal(component.busy, false);
});

test("AI reader copies the prompt and fetched Markdown with exact feedback", async () => {
  const { component, context, rowset } = loadAiReaderMenu();
  const copiedValues = [];
  rowset.copyTextToClipboard = async (value) => {
    copiedValues.push(value);
    return true;
  };
  context.fetch = async (url, options) => {
    assert.equal(url, "https://rowset.example/docs/quickstart.md");
    assert.equal(options.credentials, "same-origin");
    assert.ok(options.signal);
    return { ok: true, text: async () => "# Quickstart" };
  };

  await component.copyPrompt();
  assert.equal(component.status, "Copied");
  await component.copyMarkdown();

  assert.deepEqual(copiedValues, ["Read this Rowset page", "# Quickstart"]);
  assert.equal(component.status, "Copied");
  assert.equal(component.busy, false);
});

test("AI reader reports clipboard failure and releases the busy state", async () => {
  const { component, rowset } = loadAiReaderMenu();
  rowset.copyTextToClipboard = async () => false;

  await component.copyPrompt();

  assert.equal(component.status, "Couldn’t copy — try again");
  assert.equal(component.busy, false);
});

test("AI reader aborts a stalled Markdown request and permits retry", async () => {
  const { component, context, rowset, timers } = loadAiReaderMenu();
  rowset.copyTextToClipboard = async () => true;
  context.fetch = (_url, { signal }) =>
    new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")));
    });

  const copy = component.copyMarkdown();
  assert.equal(component.busy, true);
  assert.equal(timers.size, 1);
  timers.values().next().value();
  await copy;

  assert.equal(component.status, "Couldn’t copy — try again");
  assert.equal(component.busy, false);
});
