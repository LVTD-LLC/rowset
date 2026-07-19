import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./posthog-attribution.js", import.meta.url), "utf8");

function loadAttribution() {
  const window = { Rowset: {} };
  vm.runInNewContext(source, { window });
  return window.Rowset.posthogAttribution;
}

test("shares the bounded campaign schema across PostHog producers", () => {
  const attribution = loadAttribution();

  assert.equal(attribution.version, 1);
  assert.deepEqual([...attribution.campaignKeys], [
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "campaign_id",
  ]);
  assert.equal(attribution.safeCampaignValue(" launch-2026 "), "launch-2026");
  assert.equal(attribution.safeCampaignValue("user@example.com"), "");
  assert.equal(attribution.safeCampaignValue("x".repeat(101)), "");
});
