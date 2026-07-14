import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./alpine-components.js", import.meta.url), "utf8");

function loadAlpineComponents() {
  const components = new Map();
  const timers = new Map();
  let nextTimerId = 1;
  let initializeAlpine;
  const window = {
    clearTimeout(timerId) {
      timers.delete(timerId);
    },
    setTimeout(callback) {
      const timerId = nextTimerId;
      nextTimerId += 1;
      timers.set(timerId, callback);
      return timerId;
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
    },
    fetch: async () => ({ ok: true, text: async () => "# Markdown" }),
    navigator: {},
    window,
  });

  vm.runInContext(source, context);
  initializeAlpine();

  return { components, context, rowset: context.window.Rowset, timers, window };
}

function loadCopyPanel() {
  const loaded = loadAlpineComponents();
  return { component: loaded.components.get("copyPanel")(), rowset: loaded.rowset };
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

  assert.equal(component.status, "Copy failed");
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

  assert.equal(component.status, "Copy failed");
  assert.equal(component.busy, false);
});
