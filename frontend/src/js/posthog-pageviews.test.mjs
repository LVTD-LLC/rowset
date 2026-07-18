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
  },
  href = "https://rowset.example/pricing",
  loadAttribution = false,
  loadPrivacy = false,
  posthogReady = true,
  readyState = "complete",
  referrer = "https://news.ycombinator.com/item?id=48920229&token=secret",
} = {}) {
  const captures = [];
  const attributionUpdates = [];
  const properties = {};
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
          },
        },
      };
    }
  }
  const window = {
    DOMParser,
    Rowset: {
      posthogReady,
      updatePosthogAttribution(href = window.location.href) {
        attributionUpdates.push(href);
      },
      posthogPageviewContext: {
        contentGroup: dataset.posthogContentGroup,
        route: dataset.posthogRoute,
      },
    },
    URL,
    location,
    posthog: {
      capture(event, properties) {
        const payload = window.Rowset.sanitizePosthogEvent?.({ event, properties }) || {
          event,
          properties,
        };
        captures.push(payload);
      },
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
      unregister(name) {
        delete properties[name];
      },
    },
  };
  const context = vm.createContext({ document, URL, URLSearchParams, window });

  if (loadAttribution) {
    delete window.Rowset.updatePosthogAttribution;
    vm.runInContext(attributionSource, context);
  }
  if (loadPrivacy) {
    vm.runInContext(privacySource, context);
  }
  vm.runInContext(source, context);

  return {
    attributionUpdates,
    body,
    bodyListeners,
    captures,
    documentListeners,
    properties,
    window,
  };
}

test("captures one privacy-safe pageview for an eligible full page", () => {
  const { captures } = loadPageviews({
    href:
      "https://rowset.example/pricing?utm_source=hacker-news&utm_campaign=launch%202026&code=secret",
  });

  assert.equal(captures.length, 1);
  assert.equal(captures[0].event, "$pageview");
  assert.deepEqual({ ...captures[0].properties }, {
    $current_url: "https://rowset.example/pricing",
    $pathname: "/pricing",
    $referrer: "https://news.ycombinator.com",
    $referring_domain: "news.ycombinator.com",
    content_group: "marketing",
    route: "/pricing",
    utm_campaign: "launch 2026",
    utm_source: "hacker-news",
  });
  assert.equal(JSON.stringify(captures[0].properties).includes("secret"), false);
  assert.equal("code" in captures[0].properties, false);
});

test("updates persisted attribution before full-page and HTMX captures", () => {
  const { attributionUpdates, bodyListeners, captures, window } = loadPageviews({
    href: "https://rowset.example/pricing?campaign_id=launch-one&utm_source=hacker-news",
  });

  assert.deepEqual(attributionUpdates, [
    "https://rowset.example/pricing?campaign_id=launch-one&utm_source=hacker-news",
  ]);
  assert.equal(captures[0].properties.campaign_id, "launch-one");

  window.location = new URL(
    "https://rowset.example/docs/quickstart?campaign_id=launch-two&utm_source=newsletter",
  );
  bodyListeners.get("htmx:afterSwap")({
    detail: { xhr: { responseText: "<!doctype html><body>docs-page" } },
  });

  assert.equal(attributionUpdates.length, 2);
  assert.equal(captures[1].properties.campaign_id, "launch-two");
});

test("waits for DOM readiness before reading the server route context", () => {
  const { captures, documentListeners } = loadPageviews({ readyState: "loading" });

  assert.equal(captures.length, 0);
  documentListeners.get("DOMContentLoaded")();
  assert.equal(captures.length, 1);
});

test("waits for the real PostHog client before capturing attribution and pageviews", () => {
  const { attributionUpdates, captures, window } = loadPageviews({ posthogReady: false });

  assert.equal(captures.length, 0);
  assert.equal(attributionUpdates.length, 0);

  window.Rowset.posthogReady = true;
  window.Rowset.capturePosthogPageview();

  assert.equal(captures.length, 1);
  assert.equal(attributionUpdates.length, 1);
});

test("replays HTMX pageviews and campaign touches captured before PostHog loads", () => {
  const { attributionUpdates, bodyListeners, captures, window } = loadPageviews({
    href: "https://rowset.example/pricing?utm_source=hacker-news",
    posthogReady: false,
  });

  window.location = new URL(
    "https://rowset.example/docs/quickstart?campaign_id=docs-launch&utm_source=newsletter",
  );
  bodyListeners.get("htmx:afterSwap")({
    detail: { xhr: { responseText: "<!doctype html><body>docs-page" } },
  });

  window.Rowset.posthogReady = true;
  window.Rowset.capturePosthogPageview();

  assert.deepEqual(attributionUpdates, [
    "https://rowset.example/pricing?utm_source=hacker-news",
    "https://rowset.example/docs/quickstart?campaign_id=docs-launch&utm_source=newsletter",
  ]);
  assert.equal(captures.length, 2);
  assert.equal(captures[0].properties.utm_source, "hacker-news");
  assert.equal(captures[1].properties.campaign_id, "docs-launch");
});

test("replays pre-load pageviews through the real attribution module", () => {
  const { bodyListeners, captures, properties, window } = loadPageviews({
    href: "https://rowset.example/pricing?utm_source=hacker-news",
    loadAttribution: true,
    loadPrivacy: true,
    posthogReady: false,
  });

  window.location = new URL(
    "https://rowset.example/docs/quickstart?campaign_id=docs-launch&utm_source=newsletter",
  );
  bodyListeners.get("htmx:afterSwap")({
    detail: { xhr: { responseText: "<!doctype html><body>docs-page" } },
  });

  window.Rowset.initializePosthogAttribution(window.posthog);
  window.Rowset.posthogReady = true;
  window.Rowset.capturePosthogPageview();

  assert.equal(captures.length, 2);
  assert.equal(captures[0].properties.route, "/pricing");
  assert.equal(captures[0].properties.$pathname, "/pricing");
  assert.equal(captures[1].properties.route, "/docs/:slug");
  assert.equal(captures[1].properties.$pathname, "/docs/:slug");
  assert.equal(properties.first_touch_utm_source, "hacker-news");
  assert.equal(properties.first_touch_referring_domain, "news.ycombinator.com");
  assert.equal(properties.current_touch_utm_source, "newsletter");
  assert.equal(properties.current_touch_campaign_id, "docs-launch");
  assert.equal("current_touch_referrer" in properties, false);
});

test("does not capture private or disabled routes", () => {
  const { captures } = loadPageviews({
    dataset: {
      posthogContentGroup: "",
      posthogPageviewEnabled: "false",
      posthogRoute: "",
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
    $referrer: "https://news.ycombinator.com",
    $referring_domain: "news.ycombinator.com",
    content_group: "docs",
    route: "/docs/:slug",
    utm_medium: "social",
  });
  assert.equal(JSON.stringify(captures[1].properties).includes("secret"), false);
});

test("captures distinct HTMX navigations with the same normalized route", () => {
  const { bodyListeners, captures, window } = loadPageviews({
    dataset: {
      posthogContentGroup: "docs",
      posthogPageviewEnabled: "true",
      posthogRoute: "/docs/:slug",
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
  assert.equal(window.Rowset.posthogPageviewContext.route, "");
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
