import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./posthog-ctas.js", import.meta.url), "utf8");

test("captures a stable CTA contract without query parameters", () => {
  const listeners = {};
  const captures = [];
  const window = {
    URL,
    location: { origin: "https://rowset.example" },
    Rowset: { hasAnalyticsConsent: () => true, posthogEnvironment: "prod" },
    posthog: { capture: (...args) => captures.push(args) },
  };
  const document = { addEventListener: (name, callback) => { listeners[name] = callback; } };
  const link = {
    dataset: { posthogCta: "signup", posthogCtaLocation: "header" },
    href: "https://rowset.example/accounts/signup/?utm_source=test",
  };
  vm.runInNewContext(source, { document, window });
  listeners.click({ target: { closest: () => link } });

  assert.deepEqual(JSON.parse(JSON.stringify(captures)), [["rowset_marketing_cta_clicked", {
    event_version: 1,
    environment: "prod",
    cta_name: "signup",
    cta_location: "header",
    destination: "/accounts/signup/",
  }]]);
});

test("adds the PostHog session ID to checkout form submissions", () => {
  const listeners = {};
  const captures = [];
  const sessionInput = { value: "" };
  const form = {
    action: "https://rowset.example/create-checkout-session/1/monthly/",
    dataset: { posthogCta: "upgrade", posthogCtaLocation: "pricing_pro" },
    querySelector: () => sessionInput,
  };
  const window = {
    URL,
    location: { origin: "https://rowset.example" },
    Rowset: {
      hasAnalyticsConsent: () => true,
      posthogEnvironment: "prod",
      posthogSessionId: "session-123",
    },
    posthog: { capture: (...args) => captures.push(args) },
  };
  const document = { addEventListener: (name, callback) => { listeners[name] = callback; } };
  vm.runInNewContext(source, { document, window });

  listeners.submit({ target: { closest: () => form } });

  assert.equal(sessionInput.value, "session-123");
  assert.equal(captures.length, 1);
  assert.equal(captures[0][0], "rowset_marketing_cta_clicked");
});
