(function () {
  const Rowset = (window.Rowset = window.Rowset || {});
  const campaignKeys = Object.freeze([
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "campaign_id",
  ]);
  const version = 1;
  const campaignValuePattern = /^[a-z0-9][a-z0-9 ._\-/]*$/i;

  function safeCampaignValue(value) {
    const normalized = typeof value === "string" ? value.trim() : "";
    return normalized && normalized.length <= 100 && campaignValuePattern.test(normalized)
      ? normalized
      : "";
  }

  Rowset.posthogAttribution = Object.freeze({ campaignKeys, safeCampaignValue, version });
})();
