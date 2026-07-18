import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./posthog-privacy.js", import.meta.url), "utf8");

function loadPrivacy({ route = "/accounts/password/reset/key/:uid/:key/" } = {}) {
  const window = {
    URL,
    location: new URL("https://rowset.example/accounts/password/reset/key/user-secret/token-secret/?code=secret"),
    Rowset: {
      posthogPageviewContext: { contentGroup: "auth", route },
    },
  };
  const context = vm.createContext({
    document: {
      referrer: "https://search.example/results?q=private&token=secret",
    },
    URL,
    window,
  });

  vm.runInContext(source, context);
  return window.Rowset.sanitizePosthogEvent;
}

test("sanitizes URL, referrer, and campaign properties before PostHog sends an event", () => {
  const sanitize = loadPrivacy();
  const event = sanitize({
    event: "$pageview",
    properties: {
      $current_url:
        "https://rowset.example/accounts/password/reset/key/user-secret/token-secret/?code=secret",
      $initial_current_url:
        "https://rowset.example/accounts/password/reset/key/user-secret/token-secret/?code=secret",
      $initial_pathname: "/accounts/password/reset/key/user-secret/token-secret/",
      $initial_referrer: "https://search.example/results?q=private&token=secret",
      $initial_referring_domain: "search.example",
      $initial_utm_source: "hacker-news",
      $pathname: "/accounts/password/reset/key/user-secret/token-secret/",
      $prev_pageview_pathname: "/accounts/password/reset/key/user-secret/token-secret/",
      $referrer: "https://search.example/results?q=private&token=secret",
      $referring_domain: "search.example",
      $session_entry_pathname: "/accounts/password/reset/key/user-secret/token-secret/",
      $session_entry_referrer: "https://search.example/results?q=private&token=secret",
      $session_entry_referring_domain: "search.example",
      $session_entry_url:
        "https://rowset.example/accounts/password/reset/key/user-secret/token-secret/?code=secret",
      $session_entry_gclid: "secret-session-click-id",
      $session_entry_ph_keyword: "private search terms",
      $session_entry_utm_source: "hacker-news",
      $session_entry_utm_term: "user@example.com",
      gclid: "secret-click-id",
      ph_keyword: "private search terms",
      $utm_campaign: "launch 2026",
      $utm_term: "user@example.com",
      current_touch_campaign_id: "hn-launch",
      current_touch_referrer: "https://news.ycombinator.com/item?id=private",
      current_touch_utm_campaign: null,
      current_touch_utm_source: "hacker-news",
      first_touch_referrer: "javascript:alert(1)",
      first_touch_utm_term: "user@example.com",
      token: "required-project-token",
    },
    $set_once: {
      $initial_current_url:
        "https://rowset.example/accounts/password/reset/key/user-secret/token-secret/?code=secret",
      $initial_pathname: "/accounts/password/reset/key/user-secret/token-secret/",
      $initial_referrer: "https://search.example/results?q=private&token=secret",
      $initial_utm_source: "hacker-news",
      $initial_gclid: "secret-ad-click-id",
    },
  });

  assert.deepEqual({ ...event.properties }, {
    $current_url: "https://rowset.example/accounts/password/reset/key/:uid/:key/",
    $initial_current_url: "https://rowset.example/accounts/password/reset/key/:uid/:key/",
    $initial_pathname: "/accounts/password/reset/key/:uid/:key/",
    $initial_referrer: "https://search.example",
    $initial_referring_domain: "search.example",
    $initial_utm_source: "hacker-news",
    $pathname: "/accounts/password/reset/key/:uid/:key/",
    $referrer: "https://search.example",
    $referring_domain: "search.example",
    $session_entry_pathname: "/accounts/password/reset/key/:uid/:key/",
    $session_entry_referrer: "https://search.example",
    $session_entry_referring_domain: "search.example",
    $session_entry_url: "https://rowset.example/accounts/password/reset/key/:uid/:key/",
    $session_entry_utm_source: "hacker-news",
    $utm_campaign: "launch 2026",
    current_touch_campaign_id: "hn-launch",
    current_touch_referrer: "https://news.ycombinator.com",
    current_touch_utm_campaign: null,
    current_touch_utm_source: "hacker-news",
    token: "required-project-token",
  });
  assert.deepEqual({ ...event.$set_once }, {
    $initial_current_url: "https://rowset.example/accounts/password/reset/key/:uid/:key/",
    $initial_pathname: "/accounts/password/reset/key/:uid/:key/",
    $initial_referrer: "https://search.example",
    $initial_utm_source: "hacker-news",
  });
  assert.equal(JSON.stringify(event).includes("secret"), false);
  assert.equal("$prev_pageview_pathname" in event.properties, false);
  assert.equal("$session_entry_utm_term" in event.properties, false);
  assert.equal(event.properties.token, "required-project-token");
});

test("uses origin-only URL properties on private application routes", () => {
  const sanitize = loadPrivacy({ route: "" });
  const event = sanitize({
    event: "private_action",
    properties: {
      $current_url: "https://rowset.example/datasets/private-key/?api_key=secret",
      $pathname: "/datasets/private-key/",
    },
  });

  assert.equal(event.properties.$current_url, "https://rowset.example");
  assert.equal("$pathname" in event.properties, false);
  assert.equal(JSON.stringify(event).includes("private-key"), false);
  assert.equal(JSON.stringify(event).includes("secret"), false);
});

test("preserves null events rejected by an earlier before-send hook", () => {
  const sanitize = loadPrivacy();

  assert.equal(sanitize(null), null);
});
