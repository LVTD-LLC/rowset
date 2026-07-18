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
  const referrerKeys = ["referrer", "referring_domain"];
  const touchKeys = [...campaignKeys, ...referrerKeys];
  let includeDocumentReferrer = true;
  let lastProcessedLocation = null;
  let posthogClient = null;

  function propertyName(touch, key) {
    return `${touch}_touch_${key}`;
  }

  function touchProperties(touch, values) {
    return Object.fromEntries(
      Object.entries(values).map(([key, value]) => [propertyName(touch, key), value]),
    );
  }

  function safeCampaignValue(value) {
    const normalized = String(value || "").trim();
    return normalized && normalized.length <= 100 && campaignValuePattern.test(normalized)
      ? normalized
      : "";
  }

  function safeReferrer(value) {
    try {
      const referrer = new window.URL(String(value || ""));
      if (!["http:", "https:"].includes(referrer.protocol)) {
        return null;
      }
      return { origin: referrer.origin, domain: referrer.hostname };
    } catch (_error) {
      return null;
    }
  }

  function campaignProperties(location) {
    const properties = {};
    const searchParams = new URLSearchParams(location.search);

    campaignKeys.forEach((key) => {
      const value = safeCampaignValue(searchParams.get(key));
      if (value) {
        properties[key] = value;
      }
    });

    return properties;
  }

  function externalReferrerProperties(location) {
    const referrer = safeReferrer(document.referrer);
    if (!referrer || referrer.origin === location.origin) {
      return {};
    }
    return {
      referrer: referrer.origin,
      referring_domain: referrer.domain,
    };
  }

  function detectedTouch(location) {
    const values = {
      ...campaignProperties(location),
      ...(includeDocumentReferrer ? externalReferrerProperties(location) : {}),
    };
    includeDocumentReferrer = false;
    if (Object.keys(values).length === 0) {
      return null;
    }
    return values;
  }

  function readTouch(touch) {
    const properties = {};
    if (typeof posthogClient?.get_property !== "function") {
      return properties;
    }

    campaignKeys.forEach((key) => {
      const name = propertyName(touch, key);
      const value = safeCampaignValue(posthogClient.get_property(name));
      if (value) {
        properties[name] = value;
      }
    });

    const referrerName = propertyName(touch, "referrer");
    const referrer = safeReferrer(posthogClient.get_property(referrerName));
    if (referrer) {
      properties[referrerName] = referrer.origin;
    }

    const domainName = propertyName(touch, "referring_domain");
    const domain = String(posthogClient.get_property(domainName) || "").trim().toLowerCase();
    if (domain && safeReferrer(`https://${domain}`)?.domain === domain) {
      properties[domainName] = domain;
    }

    return properties;
  }

  function currentPersonProperties() {
    const currentTouch = readTouch("current");
    if (Object.keys(currentTouch).length === 0) {
      return {};
    }
    const properties = Object.fromEntries(
      touchKeys.map((key) => [propertyName("current", key), null]),
    );
    return { ...properties, ...currentTouch };
  }

  Rowset.getPosthogPersonAttribution = function getPosthogPersonAttribution() {
    return {
      current: currentPersonProperties(),
      first: readTouch("first"),
    };
  };

  Rowset.updatePosthogAttribution = function updatePosthogAttribution(href = window.location.href) {
    const location = new window.URL(href);
    if (location.href === lastProcessedLocation) {
      return Rowset.getPosthogPersonAttribution();
    }
    lastProcessedLocation = location.href;
    const detectedValues = detectedTouch(location);
    if (!detectedValues || typeof posthogClient?.register !== "function") {
      return Rowset.getPosthogPersonAttribution();
    }

    const currentTouch = touchProperties("current", detectedValues);
    const previousCurrent = readTouch("current");
    if (JSON.stringify(previousCurrent) === JSON.stringify(currentTouch)) {
      return Rowset.getPosthogPersonAttribution();
    }

    touchKeys.forEach((key) => {
      posthogClient.unregister?.(propertyName("current", key));
    });
    posthogClient.register(currentTouch);

    if (Object.keys(readTouch("first")).length === 0) {
      posthogClient.register_once?.(touchProperties("first", detectedValues));
    }

    const attribution = Rowset.getPosthogPersonAttribution();
    if (
      Rowset.posthogIdentified === true &&
      typeof posthogClient.setPersonProperties === "function"
    ) {
      posthogClient.setPersonProperties(attribution.current, attribution.first);
    }
    return attribution;
  };

  Rowset.initializePosthogAttribution = function initializePosthogAttribution(client) {
    posthogClient = client;
    includeDocumentReferrer = true;
    lastProcessedLocation = null;
    return Rowset.updatePosthogAttribution(
      Rowset.pendingPosthogPageviews?.[0]?.href || window.location.href,
    );
  };
})();
