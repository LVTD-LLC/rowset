(function () {
  const Rowset = (window.Rowset = window.Rowset || {});
  const campaignValuePattern = /^[a-z0-9][a-z0-9 ._\-/]*$/i;
  const campaignPropertyPattern = /^(?:\$initial_|\$session_entry_|\$)?utm_[a-z0-9_]+$/i;
  const sensitiveAttributionPropertyPattern = /^(?:\$(?:initial_|session_entry_)?)?(?:_kx|dclid|epik|fbclid|gad_source|gclsrc|gbraid|gclid|igshid|irclid|li_fat_id|mc_cid|msclkid|ph_keyword|qclid|rdt_cid|sccid|ttclid|twclid|wbraid)$/i;
  const safeCampaignProperties = new Set();
  const urlPropertyNames = {
    $current_url: "url",
    $initial_current_url: "url",
    $initial_pathname: "pathname",
    $initial_referrer: "referrer",
    $initial_referring_domain: "referringDomain",
    $pathname: "pathname",
    $prev_pageview_pathname: null,
    $referrer: "referrer",
    $referring_domain: "referringDomain",
    $session_entry_pathname: "pathname",
    $session_entry_referrer: "referrer",
    $session_entry_referring_domain: "referringDomain",
    $session_entry_url: "url",
  };

  ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"].forEach(
    (key) => {
      safeCampaignProperties.add(key);
      safeCampaignProperties.add(`$${key}`);
      safeCampaignProperties.add(`$initial_${key}`);
      safeCampaignProperties.add(`$session_entry_${key}`);
    },
  );

  function safeLocationProperties() {
    const route = Rowset.posthogPageviewContext?.route || "";
    const url = `${window.location.origin}${route}`;
    let referrer = "";
    let referringDomain = "";

    if (document.referrer) {
      try {
        const parsedReferrer = new window.URL(document.referrer);
        if (["http:", "https:"].includes(parsedReferrer.protocol)) {
          referrer = parsedReferrer.origin;
          referringDomain = parsedReferrer.hostname;
        }
      } catch (_error) {
        // Invalid referrers are omitted instead of being sent verbatim.
      }
    }

    return { pathname: route, referrer, referringDomain, url };
  }

  function sanitizeProperties(properties, locationProperties) {
    if (!properties) {
      return properties;
    }

    const sanitized = { ...properties };
    Object.entries(urlPropertyNames).forEach(([property, safeValue]) => {
      if (!(property in sanitized)) {
        return;
      }

      const value = safeValue ? locationProperties[safeValue] : "";
      if (value) {
        sanitized[property] = value;
      } else {
        delete sanitized[property];
      }
    });

    Object.keys(sanitized).forEach((property) => {
      if (sensitiveAttributionPropertyPattern.test(property)) {
        delete sanitized[property];
        return;
      }
      if (!campaignPropertyPattern.test(property)) {
        return;
      }

      const value = String(sanitized[property] || "").trim();
      if (
        !safeCampaignProperties.has(property) ||
        !value ||
        value.length > 100 ||
        !campaignValuePattern.test(value)
      ) {
        delete sanitized[property];
      } else {
        sanitized[property] = value;
      }
    });

    return sanitized;
  }

  Rowset.sanitizePosthogEvent = function sanitizePosthogEvent(event) {
    if (!event) {
      return event;
    }

    const locationProperties = safeLocationProperties();
    return {
      ...event,
      properties: sanitizeProperties(event.properties, locationProperties),
      ...(event.$set && { $set: sanitizeProperties(event.$set, locationProperties) }),
      ...(event.$set_once && {
        $set_once: sanitizeProperties(event.$set_once, locationProperties),
      }),
    };
  };
})();
