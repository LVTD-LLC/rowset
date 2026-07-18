(function () {
  const Rowset = (window.Rowset = window.Rowset || {});
  const campaignKeys = [
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "campaign_id",
  ];
  const campaignValuePattern = /^[a-z0-9][a-z0-9 ._\-/]*$/i;
  const capturedHtmxRequests = new WeakSet();
  const pendingPageviews = (Rowset.pendingPosthogPageviews =
    Rowset.pendingPosthogPageviews || []);
  let lastCaptureKey = "";

  function pageviewContext() {
    const dataset = document.body?.dataset || {};
    const route = dataset.posthogRoute || "";
    const contentGroup = dataset.posthogContentGroup || "";

    if (
      dataset.posthogPageviewEnabled !== "true" ||
      !route.startsWith("/") ||
      !contentGroup
    ) {
      return null;
    }

    return { contentGroup, route };
  }

  function campaignProperties(search) {
    const properties = {};
    const searchParams = new URLSearchParams(search);

    campaignKeys.forEach((key) => {
      const value = searchParams.get(key)?.trim() || "";
      if (value && value.length <= 100 && campaignValuePattern.test(value)) {
        properties[key] = value;
      }
    });

    return properties;
  }

  function referrerProperties() {
    if (!document.referrer) {
      return {};
    }

    try {
      const referrer = new window.URL(document.referrer);
      if (!['http:', 'https:'].includes(referrer.protocol)) {
        return {};
      }
      return {
        $referrer: referrer.origin,
        $referring_domain: referrer.hostname,
      };
    } catch (_error) {
      return {};
    }
  }

  function pageviewSnapshot(force) {
    const context = pageviewContext();
    if (!context) {
      return null;
    }
    Rowset.registerPosthogPageviewContext?.(context);
    const campaign = campaignProperties(window.location.search);
    return {
      campaign,
      context,
      force,
      href: window.location.href,
      referrer: referrerProperties(),
    };
  }

  function sendPageview(snapshot) {
    const { campaign, context, force, href, referrer } = snapshot;
    const captureKey = JSON.stringify([context.route, context.contentGroup, campaign]);
    if (force !== true && captureKey === lastCaptureKey) {
      return false;
    }

    Rowset.updatePosthogAttribution?.(href);
    const currentUrl = `${new window.URL(href).origin}${context.route}`;
    window.posthog.capture("$pageview", {
      $current_url: currentUrl,
      $pathname: context.route,
      ...referrer,
      content_group: context.contentGroup,
      route: context.route,
      ...campaign,
    });
    lastCaptureKey = captureKey;
    return true;
  }

  Rowset.capturePosthogPageview = function capturePosthogPageview(force = false) {
    const snapshot = pageviewSnapshot(force);
    if (!snapshot) {
      return false;
    }
    if (Rowset.posthogReady !== true || typeof window.posthog?.capture !== "function") {
      pendingPageviews.push(snapshot);
      return false;
    }

    let captured = false;
    while (pendingPageviews.length > 0) {
      captured = sendPageview(pendingPageviews.shift()) || captured;
    }
    return sendPageview(snapshot) || captured;
  };

  function updateContextFromHtmxResponse(event) {
    const responseText = event?.detail?.xhr?.responseText;
    if (
      typeof responseText !== "string" ||
      !responseText.toLowerCase().includes("<body") ||
      typeof window.DOMParser !== "function"
    ) {
      return null;
    }

    const responseDocument = new window.DOMParser().parseFromString(responseText, "text/html");
    const responseContext = responseDocument.body?.dataset || {};
    const dataset = document.body?.dataset;
    if (!dataset) {
      return null;
    }

    if (responseContext.posthogPageviewEnabled === "true") {
      dataset.posthogPageviewEnabled = "true";
      dataset.posthogRoute = responseContext.posthogRoute || "";
      dataset.posthogContentGroup = responseContext.posthogContentGroup || "";
      Rowset.posthogPageviewContext = {
        contentGroup: dataset.posthogContentGroup,
        route: dataset.posthogRoute,
      };
      return "eligible";
    }

    dataset.posthogPageviewEnabled = "false";
    delete dataset.posthogRoute;
    delete dataset.posthogContentGroup;
    Rowset.posthogPageviewContext = { contentGroup: "", route: "" };
    return "disabled";
  }

  function captureHtmxPageview(event) {
    const contextUpdate = updateContextFromHtmxResponse(event);
    const request = event?.detail?.xhr;
    if (contextUpdate === "eligible" && request && capturedHtmxRequests.has(request)) {
      return;
    }
    if (contextUpdate === "eligible" && request) {
      capturedHtmxRequests.add(request);
    }
    Rowset.capturePosthogPageview(contextUpdate === "eligible");
  }

  function initializePageviews() {
    Rowset.capturePosthogPageview();
    document.body?.addEventListener("htmx:afterSwap", captureHtmxPageview);
    window.addEventListener?.("popstate", Rowset.capturePosthogPageview);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializePageviews, { once: true });
  } else {
    initializePageviews();
  }
})();
