import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./posthog-consent.js", import.meta.url), "utf8");
const attributionSource = fs.readFileSync(
  new URL("./posthog-attribution.js", import.meta.url),
  "utf8",
);

function loadConsent(initialCookie = "") {
  const listeners = new Map();
  const buttons = new Map();
  const banner = { hidden: true };
  const cookies = new Map(
    initialCookie
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const separator = part.indexOf("=");
        return [part.slice(0, separator), part.slice(separator + 1)];
      }),
  );
  const calls = [];
  let distinctId = "anonymous";
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
    get: () => [...cookies].map(([name, value]) => `${name}=${value}`).join("; "),
    set: (value) => {
      const [pair, ...attributes] = value.split(";");
      const separator = pair.indexOf("=");
      const name = pair.slice(0, separator);
      const cookieValue = pair.slice(separator + 1);
      const expired = attributes.some((attribute) => attribute.trim() === "Max-Age=0");
      if (expired) cookies.delete(name);
      else cookies.set(name, cookieValue);
    },
  });
  const window = {
    Event,
    URL,
    Rowset: { posthogIdentity: { distinctId: "42", email: "user@example.com" } },
    dispatchEvent: (event) => calls.push(["dispatch", event.type]),
    location: { protocol: "https:" },
    posthog: {
      get_distinct_id: () => distinctId,
      identify: (...args) => {
        distinctId = args[0];
        calls.push(["identify", ...args]);
      },
      opt_in_capturing: () => calls.push(["opt_in"]),
      opt_out_capturing: () => calls.push(["opt_out"]),
      setPersonProperties: (...args) => calls.push(["setPersonProperties", ...args]),
    },
  };
  const context = vm.createContext({ document, window });
  vm.runInContext(attributionSource, context);
  vm.runInContext(source, context);
  return {
    banner,
    calls,
    click: (selector) => listeners.get(selector)(),
    getCookie: () => document.cookie,
    window,
  };
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
  assert.match(result.getCookie(), /^rowset_analytics_consent=granted(?:;|$)/);
  assert.deepEqual(JSON.parse(JSON.stringify(result.calls.slice(1))), [
    ["opt_in"],
    ["identify", "42", { email: "user@example.com" }],
    ["dispatch", "rowset:analytics-consent-granted"],
  ]);
});

test("identified visitors synchronize first and current touch properties after identify", () => {
  const attribution = encodeURIComponent(
    JSON.stringify({
      version: 1,
      first_touch: {
        landing_route: "/",
        utm_campaign: "launch",
        utm_source: "hacker-news",
      },
      latest_touch: {
        landing_route: "/pricing",
        utm_campaign: "return",
        utm_source: "newsletter",
      },
    }),
  );
  const result = loadConsent(
    `rowset_analytics_consent=granted; rowset_marketing_attribution=${attribution}`,
  );

  assert.deepEqual(JSON.parse(JSON.stringify(result.calls.slice(0, 2))), [
    ["opt_in"],
    ["identify", "42", { email: "user@example.com" }],
  ]);
  assert.equal(result.calls[2][0], "setPersonProperties");
  assert.equal(result.calls[2][1].current_touch_utm_source, "newsletter");
  assert.equal(result.calls[2][1].current_touch_utm_campaign, "return");
  assert.equal(result.calls[2][1].current_touch_landing_route, "/pricing");
  assert.equal(result.calls[2][2].first_touch_utm_source, "hacker-news");
  assert.equal(result.calls[2][2].first_touch_utm_campaign, "launch");
  assert.equal(result.calls[2][2].first_touch_landing_route, "/");
});

test("stored attribution is sanitized before synchronizing person properties", () => {
  const attribution = encodeURIComponent(
    JSON.stringify({
      version: 1,
      first_touch: {
        landing_route: "/pricing?email=private@example.com",
        referrer: "https://example.com/private/path?token=secret",
        referring_domain: "example.com/private",
        utm_campaign: "launch?email=private@example.com",
        utm_source: "hacker-news",
      },
      latest_touch: {
        landing_route: "/pricing",
        referrer: "https://newsletter.example/archive/42?email=private@example.com",
        referring_domain: "newsletter.example",
        utm_source: "newsletter",
      },
    }),
  );
  const result = loadConsent(
    `rowset_analytics_consent=granted; rowset_marketing_attribution=${attribution}`,
  );

  const personUpdate = result.calls[2];
  assert.equal(personUpdate[0], "setPersonProperties");
  assert.equal(personUpdate[1].current_touch_referrer, "https://newsletter.example");
  assert.equal(personUpdate[1].current_touch_landing_route, "/pricing");
  assert.equal(personUpdate[2].first_touch_referrer, "https://example.com");
  assert.equal(personUpdate[2].first_touch_utm_source, "hacker-news");
  assert.equal("first_touch_landing_route" in personUpdate[2], false);
  assert.equal("first_touch_referring_domain" in personUpdate[2], false);
  assert.equal("first_touch_utm_campaign" in personUpdate[2], false);
});

test("a later tagged navigation replaces current touch without overwriting first touch", () => {
  const attribution = encodeURIComponent(
    JSON.stringify({
      version: 1,
      first_touch: { landing_route: "/", utm_source: "hacker-news" },
      latest_touch: { landing_route: "/", utm_source: "hacker-news" },
    }),
  );
  const result = loadConsent(
    `rowset_analytics_consent=granted; rowset_marketing_attribution=${attribution}`,
  );

  result.window.Rowset.persistMarketingAttribution({
    campaign_id: "return-visit",
    landing_route: "/docs/:slug",
    utm_source: "newsletter",
  });

  const personUpdate = result.calls.at(-1);
  assert.equal(personUpdate[0], "setPersonProperties");
  assert.equal(personUpdate[1].current_touch_campaign_id, "return-visit");
  assert.equal(personUpdate[1].current_touch_utm_source, "newsletter");
  assert.equal(personUpdate[1].current_touch_utm_campaign, null);
  assert.equal(personUpdate[2].first_touch_utm_source, "hacker-news");
  assert.equal(personUpdate[2].first_touch_landing_route, "/");
});

test("an untagged navigation does not erase the current campaign touch", () => {
  const attribution = encodeURIComponent(
    JSON.stringify({
      version: 1,
      first_touch: { landing_route: "/", utm_source: "hacker-news" },
      latest_touch: { landing_route: "/", utm_source: "hacker-news" },
    }),
  );
  const result = loadConsent(
    `rowset_analytics_consent=granted; rowset_marketing_attribution=${attribution}`,
  );
  const callsBeforeNavigation = result.calls.length;

  result.window.Rowset.persistMarketingAttribution({
    landing_route: "/accounts/signup/",
  });

  assert.equal(result.calls.length, callsBeforeNavigation);
  const storedCookie = result
    .getCookie()
    .split("; ")
    .find((cookie) => cookie.startsWith("rowset_marketing_attribution="));
  const storedAttribution = JSON.parse(
    decodeURIComponent(storedCookie.slice(storedCookie.indexOf("=") + 1)),
  );
  assert.equal(storedAttribution.latest_touch.utm_source, "hacker-news");
});
