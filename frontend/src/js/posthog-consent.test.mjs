import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./posthog-consent.js", import.meta.url), "utf8");

function loadConsent(initialCookie = "") {
  const listeners = new Map();
  const buttons = new Map();
  const banner = { hidden: true };
  let cookie = initialCookie;
  const calls = [];
  const document = {
    readyState: "complete",
    querySelector(selector) {
      if (selector === "[data-analytics-consent]") return banner;
      if (!buttons.has(selector)) {
        buttons.set(selector, { addEventListener: (_name, callback) => listeners.set(selector, callback) });
      }
      return buttons.get(selector);
    },
  };
  Object.defineProperty(document, "cookie", {
    get: () => cookie,
    set: (value) => {
      cookie = value;
    },
  });
  const window = {
    Event,
    Rowset: { posthogIdentity: { distinctId: "42", email: "user@example.com" } },
    dispatchEvent: (event) => calls.push(["dispatch", event.type]),
    location: { protocol: "https:" },
    posthog: {
      get_distinct_id: () => "anonymous",
      identify: (...args) => calls.push(["identify", ...args]),
      opt_in_capturing: () => calls.push(["opt_in"]),
      opt_out_capturing: () => calls.push(["opt_out"]),
    },
  };
  vm.runInNewContext(source, { document, window });
  return { banner, calls, click: (selector) => listeners.get(selector)(), getCookie: () => cookie };
}

test("analytics is opted out and the choice is shown by default", () => {
  const result = loadConsent();
  assert.equal(result.banner.hidden, false);
  assert.deepEqual(result.calls, [["opt_out"]]);
});

test("allowing analytics opts in, identifies, persists consent, and wakes pageviews", () => {
  const result = loadConsent();
  result.click("[data-analytics-consent-accept]");
  assert.equal(result.banner.hidden, true);
  assert.match(result.getCookie(), /^rowset_analytics_consent=granted;/);
  assert.deepEqual(JSON.parse(JSON.stringify(result.calls.slice(1))), [
    ["opt_in"],
    ["identify", "42", { email: "user@example.com" }],
    ["dispatch", "rowset:analytics-consent-granted"],
  ]);
});
