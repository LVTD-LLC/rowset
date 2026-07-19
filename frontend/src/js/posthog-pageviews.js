(function () {
  const Rowset = (window.Rowset = window.Rowset || {});
  const { campaignKeys, safeCampaignValue } = Rowset.posthogAttribution;
  const capturedHtmxRequests = new WeakSet();
  let includeDocumentReferrer = true;
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
      const value = safeCampaignValue(searchParams.get(key));
      if (value) properties[key] = value;
    });

    return properties;
  }

  function referrerProperties() {
    const referrerValue = includeDocumentReferrer ? document.referrer : "";
    includeDocumentReferrer = false;
    if (!referrerValue) {
      return {};
    }

    try {
      const referrer = new window.URL(referrerValue);
      if (
        !["http:", "https:"].includes(referrer.protocol) ||
        referrer.origin === window.location.origin
      ) {
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

  Rowset.capturePosthogPageview = function capturePosthogPageview(force = false) {
    const context = pageviewContext();
    if (
      !context ||
      (typeof Rowset.hasAnalyticsConsent === "function" && !Rowset.hasAnalyticsConsent()) ||
      typeof window.posthog?.capture !== "function"
    ) {
      return false;
    }

    const campaign = campaignProperties(window.location.search);
    const captureKey = JSON.stringify([context.route, context.contentGroup, campaign]);
    if (force !== true && captureKey === lastCaptureKey) {
      return false;
    }

    const currentUrl = `${window.location.origin}${context.route}`;
    const referrer = referrerProperties();
    Rowset.persistMarketingAttribution?.({
      ...campaign,
      landing_route: context.route,
      ...(referrer.$referrer ? { referrer: referrer.$referrer } : {}),
      ...(referrer.$referring_domain
        ? { referring_domain: referrer.$referring_domain }
        : {}),
    });
    window.posthog.capture("$pageview", {
      $current_url: currentUrl,
      $pathname: context.route,
      ...referrer,
      content_group: context.contentGroup,
      environment: Rowset.posthogEnvironment || "unknown",
      event_version: 1,
      route: context.route,
      ...campaign,
    });
    lastCaptureKey = captureKey;
    return true;
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
    window.addEventListener?.("rowset:analytics-consent-granted", () => Rowset.capturePosthogPageview(true));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializePageviews, { once: true });
  } else {
    initializePageviews();
  }
})();
