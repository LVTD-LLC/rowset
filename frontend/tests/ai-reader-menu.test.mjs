import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { URL } from "node:url";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../src/js/alpine-components.js", import.meta.url), "utf8");

function loadAiReaderMenu() {
  const components = new Map();
  const listeners = new Map();
  const timers = new Map();
  let nextTimerId = 1;

  const Alpine = {
    data(name, factory) {
      components.set(name, factory);
    },
  };
  const document = {
    addEventListener(name, callback) {
      listeners.set(name, callback);
    },
  };
  const window = {
    Alpine,
    Rowset: {},
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
    Alpine,
    console: globalThis.console,
    document,
    fetch: async () => ({ ok: true, text: async () => "# Markdown" }),
    navigator: {},
    window,
  });

  vm.runInContext(source, context);
  listeners.get("alpine:init")();

  const component = components.get("aiReaderMenu")();
  component.$el = {
    dataset: {
      markdownUrl: "https://rowset.example/docs/quickstart.md",
      prompt: "Read this Rowset page",
    },
  };
  return { component, context, timers, window };
}

test("copies the prompt and fetched Markdown with exact feedback", async () => {
  const { component, context, window } = loadAiReaderMenu();
  const copiedValues = [];
  window.Rowset.copyTextToClipboard = async (value) => {
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

test("reports clipboard failure and releases the busy state", async () => {
  const { component, window } = loadAiReaderMenu();
  window.Rowset.copyTextToClipboard = async () => false;

  await component.copyPrompt();

  assert.equal(component.status, "Copy failed");
  assert.equal(component.busy, false);
});

test("aborts a stalled Markdown request and permits retry", async () => {
  const { component, context, timers, window } = loadAiReaderMenu();
  window.Rowset.copyTextToClipboard = async () => true;
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
