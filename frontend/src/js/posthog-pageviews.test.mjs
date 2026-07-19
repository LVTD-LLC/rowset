import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./posthog-pageviews.js", import.meta.url), "utf8");
const attributionSource = fs.readFileSync(
  new URL("./posthog-attribution.js", import.meta.url),
  "utf8",
);
const privacySource = fs.readFileSync(new URL("./posthog-privacy.js", import.meta.url), "utf8");

function loadPageviews({
  dataset = {
    posthogContentGroup: "marketing",
    posthogPageviewEnabled: "true",
    posthogRoute: "/pricing",
    posthogTrafficCategory: "human",
  },
  href = "https://rowset.example/pricing",
  loadPrivacy = false,
  readyState = "complete",
  referrer = "https://news.ycombinator.com/item?id=48920229&token=secret",
} = {}) {
  const captures = [];
  const attributionTouches = [];
  const documentListeners = new Map();
  const bodyListeners = new Map();
  const location = new URL(href);
  const body = {
    dataset: { ...dataset },
    addEventListener(name, callback) {
      bodyListeners.set(name, callback);
    },
  };
  const document = {
    body,
    readyState,
    referrer,
    addEventListener(name, callback) {
      documentListeners.set(name, callback);
    },
  };
  class DOMParser {
    parseFromString(responseText) {
      if (!responseText.includes("docs-page")) {
        return { body: { dataset: {} } };
      }
      return {
        body: {
          dataset: {
            posthogContentGroup: "docs",
            posthogPageviewEnabled: "true",
            posthogRoute: "/docs/:slug",
            posthogTrafficCategory: "ai_agent",
          },
        },
      };
    }
  }
  const window = {
    DOMParser,
    Rowset: {
      persistMarketingAttribution(touch) {
        attributionTouches.push(touch);
      },
      posthogPageviewContext: {
        contentGroup: dataset.posthogContentGroup,
        route: dataset.posthogRoute,
        trafficCategory: dataset.posthogTrafficCategory,
      },
    },
    URL,
    location,
    posthog: {
      capture(event, properties) {
        captures.push({ event, properties });
      },
    },
  };
  const context = vm.createContext({ document, URL, URLSearchParams, window });

  vm.runInContext(attributionSource, context);
  if (loadPrivacy) {
    vm.runInContext(privacySource, context);
  }
  vm.runInContext(source, context);

  return { attributionTouches, body, bodyListeners, captures, documentListeners, window };
}

test("captures one privacy-safe pageview for an eligible full page", () => {
  const { attributionTouches, captures } = loadPageviews({
    href:
      "https://rowset.example/pricing?utm_source=hacker-news&utm_campaign=launch%202026&campaign_id=hn-launch&code=secret",
  });

  assert.equal(captures.length, 1);
  assert.equal(captures[0].event, "$pageview");
  assert.deepEqual({ ...captures[0].properties }, {
    $current_url: "https://rowset.example/pricing",
    $pathname: "/pricing",
    $referrer: "https://news.ycombinator.com",
    $referring_domain: "news.ycombinator.com",
    campaign_id: "hn-launch",
    content_group: "marketing",
    environment: "unknown",
    event_version: 1,
    route: "/pricing",
    traffic_category: "human",
    utm_campaign: "launch 2026",
    utm_source: "hacker-news",
  });
  assert.equal(JSON.stringify(captures[0].properties).includes("secret"), false);
  assert.equal("code" in captures[0].properties, false);
  assert.deepEqual(JSON.parse(JSON.stringify(attributionTouches)), [
    {
      campaign_id: "hn-launch",
      landing_route: "/pricing",
      referrer: "https://news.ycombinator.com",
      referring_domain: "news.ycombinator.com",
      utm_campaign: "launch 2026",
      utm_source: "hacker-news",
    },
  ]);
});

test("waits for DOM readiness before reading the server route context", () => {
  const { captures, documentListeners } = loadPageviews({ readyState: "loading" });

  assert.equal(captures.length, 0);
  documentListeners.get("DOMContentLoaded")();
  assert.equal(captures.length, 1);
});

test("does not capture private or disabled routes", () => {
  const { captures } = loadPageviews({
    dataset: {
      posthogContentGroup: "",
      posthogPageviewEnabled: "false",
      posthogRoute: "",
      posthogTrafficCategory: "unknown_automation",
    },
    href: "https://rowset.example/datasets/",
  });

  assert.equal(captures.length, 0);
});

test("deduplicates repeated HTMX swaps for the same route", () => {
  const { bodyListeners, captures } = loadPageviews();

  bodyListeners.get("htmx:afterSwap")({});
  bodyListeners.get("htmx:afterSwap")({});

  assert.equal(captures.length, 1);
});

test("captures a new normalized route once after an HTMX navigation", () => {
  const { bodyListeners, captures, window } = loadPageviews();

  window.location = new URL(
    "https://rowset.example/docs/authentication?utm_medium=social&reset_token=secret",
  );
  bodyListeners.get("htmx:afterSwap")({
    detail: { xhr: { responseText: "<!doctype html><body>docs-page" } },
  });
  bodyListeners.get("htmx:afterSwap")({});

  assert.equal(captures.length, 2);
  assert.deepEqual({ ...captures[1].properties }, {
    $current_url: "https://rowset.example/docs/:slug",
    $pathname: "/docs/:slug",
    content_group: "docs",
    environment: "unknown",
    event_version: 1,
    route: "/docs/:slug",
    traffic_category: "ai_agent",
    utm_medium: "social",
  });
  assert.equal(JSON.stringify(captures[1].properties).includes("secret"), false);
  assert.deepEqual(JSON.parse(JSON.stringify(window.Rowset.posthogPageviewContext)), {
    contentGroup: "docs",
    route: "/docs/:slug",
    trafficCategory: "ai_agent",
  });
});

test("persists a tagged HTMX navigation without reusing the landing referrer", () => {
  const { attributionTouches, bodyListeners, window } = loadPageviews();

  window.location = new URL(
    "https://rowset.example/docs/authentication?campaign_id=docs-return&utm_source=newsletter",
  );
  bodyListeners.get("htmx:afterSwap")({
    detail: { xhr: { responseText: "<!doctype html><body>docs-page" } },
  });

  assert.deepEqual(JSON.parse(JSON.stringify(attributionTouches[1])), {
    campaign_id: "docs-return",
    landing_route: "/docs/:slug",
    utm_source: "newsletter",
  });
});

test("captures distinct HTMX navigations with the same normalized route", () => {
  const { bodyListeners, captures, window } = loadPageviews({
    dataset: {
      posthogContentGroup: "docs",
      posthogPageviewEnabled: "true",
      posthogRoute: "/docs/:slug",
      posthogTrafficCategory: "human",
    },
    href: "https://rowset.example/docs/getting-started",
  });
  const secondNavigation = {
    detail: { xhr: { responseText: "<!doctype html><body>docs-page" } },
  };

  window.location = new URL("https://rowset.example/docs/authentication");
  bodyListeners.get("htmx:afterSwap")(secondNavigation);
  bodyListeners.get("htmx:afterSwap")(secondNavigation);

  assert.equal(captures.length, 2);
  assert.equal(captures[1].properties.route, "/docs/:slug");
});

test("disables capture after an HTMX transition to a private route", () => {
  const { body, bodyListeners, captures, window } = loadPageviews();

  window.location = new URL("https://rowset.example/datasets/private-id/");
  bodyListeners.get("htmx:afterSwap")({
    detail: { xhr: { responseText: "<!doctype html><body>private-page" } },
  });

  assert.equal(captures.length, 1);
  assert.equal(body.dataset.posthogPageviewEnabled, "false");
  assert.equal("posthogRoute" in body.dataset, false);
  assert.equal("posthogContentGroup" in body.dataset, false);
  assert.equal("posthogTrafficCategory" in body.dataset, false);
  assert.deepEqual(JSON.parse(JSON.stringify(window.Rowset.posthogPageviewContext)), {
    contentGroup: "",
    route: "",
    trafficCategory: "",
  });
});

test("keeps the privacy hook in sync with HTMX route changes", () => {
  const { bodyListeners, window } = loadPageviews({ loadPrivacy: true });

  window.location = new URL("https://rowset.example/docs/authentication?token=secret");
  bodyListeners.get("htmx:afterSwap")({
    detail: { xhr: { responseText: "<!doctype html><body>docs-page" } },
  });

  const sanitized = window.Rowset.sanitizePosthogEvent({
    event: "$pageview",
    properties: {
      $current_url: window.location.href,
      $pathname: window.location.pathname,
    },
  });

  assert.equal(sanitized.properties.$current_url, "https://rowset.example/docs/:slug");
  assert.equal(sanitized.properties.$pathname, "/docs/:slug");
  assert.equal(JSON.stringify(sanitized).includes("secret"), false);
});

test("drops unsafe or unbounded campaign values", () => {
  const { captures } = loadPageviews({
    href: `https://rowset.example/pricing?utm_source=${"x".repeat(101)}&utm_term=user%40example.com&utm_content=launch_v2`,
  });

  assert.equal("utm_source" in captures[0].properties, false);
  assert.equal("utm_term" in captures[0].properties, false);
  assert.equal(captures[0].properties.utm_content, "launch_v2");
});
