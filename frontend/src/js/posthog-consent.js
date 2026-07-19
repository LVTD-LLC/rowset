(function () {
  const Rowset = (window.Rowset = window.Rowset || {});
  const consentCookie = "rowset_analytics_consent";
  const attributionCookie = "rowset_marketing_attribution";
  const { campaignKeys, safeCampaignValue } = Rowset.posthogAttribution;
  const attributionSignalKeys = [...campaignKeys, "referrer", "referring_domain"];
  const touchKeys = [
    ...campaignKeys,
    "landing_route",
    "referrer",
    "referring_domain",
  ];
  const domainPattern = /^[a-z0-9.-]+$/i;

  function cookieValue(name) {
    const prefix = `${name}=`;
    return (document.cookie || "")
      .split(";")
      .map((part) => part.trim())
      .find((part) => part.startsWith(prefix))
      ?.slice(prefix.length) || "";
  }

  function setCookie(name, value, maxAge) {
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${name}=${value}; Path=/; Max-Age=${maxAge}; SameSite=Lax${secure}`;
  }

  function showBanner(show) {
    const banner = document.querySelector("[data-analytics-consent]");
    if (banner) banner.hidden = !show;
  }

  function safeReferrer(value) {
    try {
      const referrer = new window.URL(String(value || ""));
      return ["http:", "https:"].includes(referrer.protocol) ? referrer.origin : "";
    } catch (_error) {
      return "";
    }
  }

  function sanitizeTouch(touch) {
    if (!touch || typeof touch !== "object") return {};
    const sanitized = {};
    campaignKeys.forEach((key) => {
      const value = safeCampaignValue(touch[key]);
      if (value) sanitized[key] = value;
    });
    const route = typeof touch.landing_route === "string" ? touch.landing_route : "";
    if (route.startsWith("/") && !route.includes("?") && route.length <= 160) {
      sanitized.landing_route = route;
    }
    const referrer = safeReferrer(touch.referrer);
    if (referrer) sanitized.referrer = referrer;
    const domain =
      typeof touch.referring_domain === "string"
        ? touch.referring_domain.trim().toLowerCase()
        : "";
    if (domain && domain.length <= 253 && domainPattern.test(domain)) {
      sanitized.referring_domain = domain;
    }
    return sanitized;
  }

  function readMarketingAttribution() {
    try {
      const stored = JSON.parse(decodeURIComponent(cookieValue(attributionCookie))) || {};
      if (stored.version !== 1) return {};
      const firstTouch = sanitizeTouch(stored.first_touch);
      const latestTouch = sanitizeTouch(stored.latest_touch);
      return {
        first_touch: firstTouch,
        latest_touch: latestTouch,
      };
    } catch (_error) {
      return {};
    }
  }

  function personAttribution(attribution = readMarketingAttribution()) {
    const firstTouch = attribution.first_touch || {};
    const currentTouch = attribution.latest_touch || {};
    if (Object.keys(firstTouch).length === 0 && Object.keys(currentTouch).length === 0) {
      return { current: {}, first: {} };
    }
    const current = Object.fromEntries(
      touchKeys.map((key) => [`current_touch_${key}`, null]),
    );
    Object.entries(currentTouch).forEach(([key, value]) => {
      current[`current_touch_${key}`] = value;
    });
    const first = Object.fromEntries(
      Object.entries(firstTouch).map(([key, value]) => [`first_touch_${key}`, value]),
    );
    return { current, first };
  }

  Rowset.syncPosthogIdentityAndAttribution = function syncPosthogIdentityAndAttribution(
    attribution = readMarketingAttribution(),
  ) {
    if (!Rowset.hasAnalyticsConsent()) return;
    const identity = Rowset.posthogIdentity || {};
    if (!identity.distinctId) return;
    if (window.posthog?.get_distinct_id?.() !== identity.distinctId) {
      window.posthog?.identify?.(identity.distinctId, { email: identity.email });
    }
    const properties = personAttribution(attribution);
    if (
      (Object.keys(properties.current).length > 0 || Object.keys(properties.first).length > 0) &&
      typeof window.posthog?.setPersonProperties === "function"
    ) {
      window.posthog.setPersonProperties(properties.current, properties.first);
    }
  };

  Rowset.analyticsConsent = cookieValue(consentCookie);
  Rowset.hasAnalyticsConsent = () => Rowset.analyticsConsent === "granted";
  Rowset.persistMarketingAttribution = function persistMarketingAttribution(touch) {
    if (!Rowset.hasAnalyticsConsent()) return;
    const sanitized = sanitizeTouch(touch);
    if (Object.keys(sanitized).length === 0) return;
    const existing = readMarketingAttribution();
    const hasFirstTouch = Object.keys(existing.first_touch || {}).length > 0;
    const hasAttributionSignal = attributionSignalKeys.some((key) => key in sanitized);
    if (hasFirstTouch && !hasAttributionSignal) return;
    const attribution = {
      version: 1,
      first_touch: hasFirstTouch ? existing.first_touch : sanitized,
      latest_touch: sanitized,
    };
    setCookie(attributionCookie, encodeURIComponent(JSON.stringify(attribution)), 60 * 60 * 24 * 180);
    Rowset.syncPosthogIdentityAndAttribution(attribution);
  };

  function choose(value) {
    Rowset.analyticsConsent = value;
    setCookie(consentCookie, value, 60 * 60 * 24 * 365);
    showBanner(false);
    if (value === "granted") {
      window.posthog?.opt_in_capturing?.();
      Rowset.syncPosthogIdentityAndAttribution();
      window.dispatchEvent?.(new window.Event("rowset:analytics-consent-granted"));
    } else {
      window.posthog?.opt_out_capturing?.();
      setCookie(attributionCookie, "", 0);
    }
  }

  function initialize() {
    document.querySelector("[data-analytics-consent-accept]")?.addEventListener("click", () => choose("granted"));
    document.querySelector("[data-analytics-consent-decline]")?.addEventListener("click", () => choose("denied"));
    if (Rowset.analyticsConsent === "granted") {
      window.posthog?.opt_in_capturing?.();
      Rowset.syncPosthogIdentityAndAttribution();
      showBanner(false);
    } else {
      window.posthog?.opt_out_capturing?.();
      showBanner(Rowset.analyticsConsent !== "denied");
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
  else initialize();
})();
