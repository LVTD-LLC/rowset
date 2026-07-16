import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./posthog-identity.js", import.meta.url), "utf8");

function loadPosthogIdentity() {
  const listeners = new Map();
  let resetCount = 0;
  const window = {
    posthog: {
      reset() {
        resetCount += 1;
      },
    },
  };
  const context = vm.createContext({
    document: {
      addEventListener(name, callback) {
        listeners.set(name, callback);
      },
    },
    window,
  });

  vm.runInContext(source, context);

  return { listeners, resetCount: () => resetCount, rowset: window.Rowset };
}

test("explicit logout resets PostHog identity", () => {
  const { listeners, resetCount } = loadPosthogIdentity();

  listeners.get("submit")({
    target: { matches: (selector) => selector === "form[data-posthog-reset]" },
  });

  assert.equal(resetCount(), 1);
});

test("ordinary form navigation preserves PostHog identity", () => {
  const { listeners, resetCount } = loadPosthogIdentity();

  listeners.get("submit")({ target: { matches: () => false } });

  assert.equal(resetCount(), 0);
});
