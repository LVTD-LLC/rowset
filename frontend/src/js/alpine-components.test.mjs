import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./alpine-components.js", import.meta.url), "utf8");

function loadCopyPanel() {
  const components = new Map();
  let initializeAlpine;
  const context = vm.createContext({
    Alpine: {
      data(name, factory) {
        components.set(name, factory);
      },
    },
    document: {
      addEventListener(name, callback) {
        if (name === "alpine:init") {
          initializeAlpine = callback;
        }
      },
    },
    window: {},
  });

  vm.runInContext(source, context);
  initializeAlpine();

  return {
    component: components.get("copyPanel")(),
    rowset: context.window.Rowset,
  };
}

async function runCopy({ copied }) {
  const { component, rowset } = loadCopyPanel();
  const dispatched = [];
  component.$el = {
    dataset: { copySuccessEvent: "agent-setup-prompt-copied" },
  };
  component.$dispatch = (...args) => dispatched.push(args);
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
  assert.equal(dispatched[0][0], "agent-setup-prompt-copied");
  assert.equal(dispatched[0][1], null);
  assert.deepEqual({ ...dispatched[0][2] }, { composed: false, cancelable: false });
  assert.equal(component.busy, false);
});

test("failed clipboard copy leaves prompt task incomplete", async () => {
  const { component, dispatched } = await runCopy({ copied: false });

  assert.deepEqual(dispatched, []);
  assert.equal(component.busy, false);
});
