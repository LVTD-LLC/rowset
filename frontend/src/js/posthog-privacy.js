(function () {
  const Rowset = (window.Rowset = window.Rowset || {});
  const campaignValuePattern = /^[a-z0-9][a-z0-9 ._\-/]*$/i;
  const campaignPropertyPattern =
    /^(?:\$initial_|\$session_entry_|\$)?(?:utm_[a-z0-9_]+|campaign_id)$/i;
  const touchAttributionPropertyPattern =
    /^(?:first|current)_touch_(?:campaign_id|utm_source|utm_medium|utm_campaign|utm_content|utm_term|referrer|referring_domain)$/;
  const sensitiveAttributionPropertyPattern = /^(?:\$(?:initial_|session_entry_)?)?(?:_kx|dclid|epik|fbclid|gad_source|gclsrc|gbraid|gclid|igshid|irclid|li_fat_id|mc_cid|msclkid|ph_keyword|qclid|rdt_cid|sccid|ttclid|twclid|wbraid)$/i;
  const safeCampaignProperties = new Set();
  const safePageviewContexts = new Map();
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

  ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "campaign_id"].forEach(
    (key) => {
      safeCampaignProperties.add(key);
      safeCampaignProperties.add(`$${key}`);
      safeCampaignProperties.add(`$initial_${key}`);
      safeCampaignProperties.add(`$session_entry_${key}`);
    },
  );

  function contextKey(context) {
    return `${context.contentGroup}\u0000${context.route}`;
  }

  Rowset.registerPosthogPageviewContext = function registerPosthogPageviewContext(context) {
    const contentGroup = String(context?.contentGroup || "");
    const route = String(context?.route || "");
    if (
      /^[a-z0-9_-]{1,50}$/i.test(contentGroup) &&
      route.length <= 200 &&
      /^\/[a-z0-9_:/.-]*$/i.test(route)
    ) {
      safePageviewContexts.set(contextKey({ contentGroup, route }), route);
    }
  };
  Rowset.registerPosthogPageviewContext(Rowset.posthogPageviewContext);

  function safeLocationProperties(eventProperties) {
    const eventContext = {
      contentGroup: eventProperties?.content_group,
      route: eventProperties?.route,
    };
    const currentContext = Rowset.posthogPageviewContext || {};
    const route =
      safePageviewContexts.get(contextKey(eventContext)) ||
      safePageviewContexts.get(contextKey(currentContext)) ||
      "";
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

  function sanitizeTouchAttributionValue(property, rawValue) {
    const value = String(rawValue || "").trim();
    if (property.endsWith("_referrer")) {
      try {
        const referrer = new window.URL(value);
        return ["http:", "https:"].includes(referrer.protocol) ? referrer.origin : null;
      } catch (_error) {
        return null;
      }
    }

    if (property.endsWith("_referring_domain")) {
      try {
        const domain = value.toLowerCase();
        const parsedDomain = new window.URL(`https://${domain}`);
        return domain && parsedDomain.hostname === domain ? domain : null;
      } catch (_error) {
        return null;
      }
    }

    return value && value.length <= 100 && campaignValuePattern.test(value) ? value : null;
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
      if (touchAttributionPropertyPattern.test(property)) {
        if (property.startsWith("current_touch_") && sanitized[property] === null) {
          return;
        }
        const value = sanitizeTouchAttributionValue(property, sanitized[property]);
        if (value === null) {
          delete sanitized[property];
        } else {
          sanitized[property] = value;
        }
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

    const locationProperties = safeLocationProperties(event.properties);
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
