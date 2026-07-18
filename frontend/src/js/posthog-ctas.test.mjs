import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./posthog-ctas.js", import.meta.url), "utf8");

test("captures a stable CTA contract without query parameters", () => {
  let click;
  const captures = [];
  const window = {
    URL,
    location: { origin: "https://rowset.example" },
    Rowset: { hasAnalyticsConsent: () => true, posthogEnvironment: "prod" },
    posthog: { capture: (...args) => captures.push(args) },
  };
  const document = { addEventListener: (_name, callback) => { click = callback; } };
  const link = {
    dataset: { posthogCta: "signup", posthogCtaLocation: "header" },
    href: "https://rowset.example/accounts/signup/?utm_source=test",
  };
  vm.runInNewContext(source, { document, window });
  click({ target: { closest: () => link } });

  assert.deepEqual(JSON.parse(JSON.stringify(captures)), [["rowset_marketing_cta_clicked", {
    event_version: 1,
    environment: "prod",
    cta_name: "signup",
    cta_location: "header",
    destination: "/accounts/signup/",
  }]]);
});
