(function () {
  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("[data-posthog-cta]");
    if (!link || !window.Rowset?.hasAnalyticsConsent?.()) return;
    let destination = "";
    try {
      destination = new window.URL(link.href, window.location.origin).pathname;
    } catch (_error) {
      // An invalid destination is represented by the empty allowlisted value.
    }
    window.posthog?.capture?.("rowset_marketing_cta_clicked", {
      event_version: 1,
      environment: window.Rowset.posthogEnvironment || "unknown",
      cta_name: link.dataset.posthogCta,
      cta_location: link.dataset.posthogCtaLocation || "unknown",
      destination,
    });
  });
})();
