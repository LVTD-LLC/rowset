(function () {
  const Rowset = (window.Rowset = window.Rowset || {});
  const consentCookie = "rowset_analytics_consent";
  const attributionCookie = "rowset_marketing_attribution";

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

  Rowset.analyticsConsent = cookieValue(consentCookie);
  Rowset.hasAnalyticsConsent = () => Rowset.analyticsConsent === "granted";
  Rowset.persistMarketingAttribution = function persistMarketingAttribution(touch) {
    if (!Rowset.hasAnalyticsConsent() || !touch || Object.keys(touch).length === 0) return;
    let existing = {};
    try {
      existing = JSON.parse(decodeURIComponent(cookieValue(attributionCookie))) || {};
    } catch (_error) {
      // Ignore malformed or stale attribution written by an older client.
    }
    const attribution = {
      version: 1,
      first_touch: existing.first_touch || touch,
      latest_touch: touch,
    };
    setCookie(attributionCookie, encodeURIComponent(JSON.stringify(attribution)), 60 * 60 * 24 * 180);
  };

  function choose(value) {
    Rowset.analyticsConsent = value;
    setCookie(consentCookie, value, 60 * 60 * 24 * 365);
    showBanner(false);
    if (value === "granted") {
      window.posthog?.opt_in_capturing?.();
      const identity = Rowset.posthogIdentity || {};
      if (identity.distinctId && window.posthog?.get_distinct_id?.() !== identity.distinctId) {
        window.posthog?.identify?.(identity.distinctId, { email: identity.email });
      }
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
      const identity = Rowset.posthogIdentity || {};
      if (identity.distinctId && window.posthog?.get_distinct_id?.() !== identity.distinctId) {
        window.posthog?.identify?.(identity.distinctId, { email: identity.email });
      }
      showBanner(false);
    } else {
      window.posthog?.opt_out_capturing?.();
      showBanner(Rowset.analyticsConsent !== "denied");
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
  else initialize();
})();
