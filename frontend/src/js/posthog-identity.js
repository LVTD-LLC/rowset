(function () {
  const Rowset = (window.Rowset = window.Rowset || {});

  Rowset.resetPosthogOnLogout = function resetPosthogOnLogout(event) {
    if (event.target.matches("form[data-posthog-reset]")) {
      window.posthog?.reset?.();
    }
  };

  document.addEventListener("submit", Rowset.resetPosthogOnLogout);
})();
