import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./posthog-attribution.js", import.meta.url), "utf8");

function loadAttribution({
  href = "https://rowset.example/pricing",
  identified = false,
  referrer = "",
} = {}) {
  const personUpdates = [];
  const properties = {};
  const posthog = {
    get_property(name) {
      return properties[name];
    },
    register(values) {
      Object.assign(properties, values);
    },
    register_once(values) {
      Object.entries(values).forEach(([name, value]) => {
        if (!(name in properties)) {
          properties[name] = value;
        }
      });
    },
    setPersonProperties(current, first) {
      personUpdates.push({ current, first });
    },
    unregister(name) {
      delete properties[name];
    },
  };
  const document = { referrer };
  const window = {
    Rowset: { posthogIdentified: identified },
    URL,
    location: new URL(href),
    posthog,
  };
  const context = vm.createContext({ document, URL, URLSearchParams, window });

  vm.runInContext(source, context);

  return { document, personUpdates, properties, window };
}

test("persists bounded first-touch and current campaign attribution", () => {
  const { properties, window } = loadAttribution({
    href:
      "https://rowset.example/pricing?utm_source=hacker-news&utm_campaign=launch%202026&campaign_id=hn-launch&code=secret&utm_term=user%40example.com",
    referrer: "https://news.ycombinator.com/item?id=48920229&token=secret",
  });

  window.Rowset.initializePosthogAttribution(window.posthog);

  assert.deepEqual(properties, {
    current_touch_campaign_id: "hn-launch",
    current_touch_referrer: "https://news.ycombinator.com",
    current_touch_referring_domain: "news.ycombinator.com",
    current_touch_utm_campaign: "launch 2026",
    current_touch_utm_source: "hacker-news",
    first_touch_campaign_id: "hn-launch",
    first_touch_referrer: "https://news.ycombinator.com",
    first_touch_referring_domain: "news.ycombinator.com",
    first_touch_utm_campaign: "launch 2026",
    first_touch_utm_source: "hacker-news",
  });
  assert.equal(JSON.stringify(properties).includes("secret"), false);
  assert.equal(JSON.stringify(properties).includes("user@example.com"), false);
});

test("does not replace an external referrer when the same location is processed twice", () => {
  const { properties, window } = loadAttribution({
    href: "https://rowset.example/pricing?utm_source=hacker-news",
    referrer: "https://news.ycombinator.com/item?id=48920229",
  });

  window.Rowset.initializePosthogAttribution(window.posthog);
  window.Rowset.updatePosthogAttribution();

  assert.equal(properties.current_touch_utm_source, "hacker-news");
  assert.equal(properties.current_touch_referrer, "https://news.ycombinator.com");
  assert.equal(properties.current_touch_referring_domain, "news.ycombinator.com");
});

test("keeps the first touch and replaces the complete current-touch snapshot", () => {
  const { properties, window } = loadAttribution({
    href: "https://rowset.example/?utm_source=hacker-news&utm_campaign=launch",
    referrer: "https://news.ycombinator.com/item?id=48920229",
  });

  window.Rowset.initializePosthogAttribution(window.posthog);
  window.location = new URL(
    "https://rowset.example/docs/quickstart?utm_source=newsletter&utm_medium=email",
  );
  window.Rowset.updatePosthogAttribution();

  assert.equal(properties.first_touch_utm_source, "hacker-news");
  assert.equal(properties.first_touch_utm_campaign, "launch");
  assert.equal(properties.first_touch_referring_domain, "news.ycombinator.com");
  assert.equal(properties.current_touch_utm_source, "newsletter");
  assert.equal(properties.current_touch_utm_medium, "email");
  assert.equal("current_touch_utm_campaign" in properties, false);
  assert.equal("current_touch_referrer" in properties, false);
  assert.equal("current_touch_referring_domain" in properties, false);
});

test("does not reuse the full-page referrer on an untagged HTMX navigation", () => {
  const { properties, window } = loadAttribution({
    href: "https://rowset.example/?utm_source=hacker-news",
    referrer: "https://news.ycombinator.com/item?id=48920229",
  });

  window.Rowset.initializePosthogAttribution(window.posthog);
  window.location = new URL("https://rowset.example/accounts/signup/");
  window.Rowset.updatePosthogAttribution();

  assert.equal(properties.first_touch_utm_source, "hacker-news");
  assert.equal(properties.current_touch_utm_source, "hacker-news");
});

test("syncs a new HTMX touch to an already identified person", () => {
  const { personUpdates, window } = loadAttribution({
    href: "https://rowset.example/?utm_source=hacker-news&utm_campaign=launch",
    referrer: "https://news.ycombinator.com/item?id=48920229",
  });

  window.Rowset.initializePosthogAttribution(window.posthog);
  window.Rowset.posthogIdentified = true;
  window.location = new URL(
    "https://rowset.example/docs/quickstart?campaign_id=docs-launch&utm_source=newsletter",
  );
  window.Rowset.updatePosthogAttribution();

  assert.equal(personUpdates.length, 1);
  assert.equal(personUpdates[0].current.current_touch_campaign_id, "docs-launch");
  assert.equal(personUpdates[0].current.current_touch_utm_source, "newsletter");
  assert.equal(personUpdates[0].current.current_touch_utm_campaign, null);
  assert.equal(personUpdates[0].first.first_touch_utm_source, "hacker-news");
  assert.equal(personUpdates[0].first.first_touch_utm_campaign, "launch");
});

test("returns revalidated person properties for the identify boundary", () => {
  const { properties, window } = loadAttribution({
    href: "https://rowset.example/?utm_source=hacker-news",
  });

  window.Rowset.initializePosthogAttribution(window.posthog);
  properties.first_touch_utm_campaign = "user@example.com";
  properties.current_touch_referrer = "javascript:alert(1)";

  const attribution = window.Rowset.getPosthogPersonAttribution();

  assert.equal(attribution.first.first_touch_utm_source, "hacker-news");
  assert.equal("first_touch_utm_campaign" in attribution.first, false);
  assert.equal(attribution.current.current_touch_utm_source, "hacker-news");
  assert.equal(attribution.current.current_touch_utm_campaign, null);
  assert.equal(attribution.current.current_touch_referrer, null);
});

test("does not clear person attribution for an untagged fresh identity", () => {
  const { window } = loadAttribution({ href: "https://rowset.example/accounts/login/" });

  const attribution = window.Rowset.initializePosthogAttribution(window.posthog);

  assert.deepEqual({ ...attribution.current }, {});
  assert.deepEqual({ ...attribution.first }, {});
});
