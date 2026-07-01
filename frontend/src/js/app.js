(function () {
  const Rowset = (window.Rowset = window.Rowset || {});
  const DEFAULT_TIMEOUT_MS = 8000;
  const EXIT_DURATION_MS = 200;
  const messageStates = new WeakMap();

  Rowset.copyTextToClipboard =
    Rowset.copyTextToClipboard ||
    async function copyTextToClipboard(text, { sourceElement } = {}) {
      if (!text) {
        return false;
      }

      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(text);
          return true;
        } catch (_error) {
          // Fall back when clipboard permissions are unavailable.
        }
      }

      if (sourceElement && typeof sourceElement.select === "function") {
        sourceElement.focus();
        sourceElement.select();
        try {
          return document.execCommand("copy");
        } catch (_error) {
          return false;
        }
      }

      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.top = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();

      try {
        return document.execCommand("copy");
      } catch (_error) {
        return false;
      } finally {
        textarea.remove();
      }
    };

  function onReady(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback, { once: true });
    } else {
      callback();
    }
  }

  function csrfToken() {
    return document.body?.dataset.csrfToken || "";
  }

  function configureHtmx() {
    if (!window.htmx) {
      return;
    }

    window.htmx.config.historyRestoreAsHxRequest = false;
    document.body?.addEventListener("htmx:configRequest", (event) => {
      event.detail.headers["X-CSRFToken"] = csrfToken();
    });
  }

  function initializeAlpineTree(root) {
    if (root?.nodeType !== 1 || typeof window.Alpine?.initTree !== "function") {
      return;
    }

    window.Alpine.initTree(root);
  }

  function fetchUserSettings() {
    const url = document.body?.dataset.userSettingsUrl;
    if (!url) {
      return;
    }

    const abortController = new AbortController();
    fetch(url, { signal: abortController.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data) {
          localStorage.setItem("userSettings", JSON.stringify(data));
        }
      })
      .catch(() => {});
  }

  function shouldAutoDismiss(item) {
    return item.dataset.messageAutoDismiss !== "false" && item.getAttribute("role") !== "alert";
  }

  function timeoutFor(item) {
    const timeout = Number.parseInt(item.dataset.messageTimeout || "", 10);
    return Number.isFinite(timeout) && timeout > 0 ? timeout : DEFAULT_TIMEOUT_MS;
  }

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function clearDismissal(state) {
    if (state.timeoutId) {
      window.clearTimeout(state.timeoutId);
      state.timeoutId = null;
    }
    state.abortController.abort();
  }

  function hideMessage(item) {
    const state = messageStates.get(item);
    if (state) {
      clearDismissal(state);
      messageStates.delete(item);
    }

    item.setAttribute("aria-hidden", "true");
    if (prefersReducedMotion()) {
      item.remove();
      return;
    }

    item.classList.add("translate-x-full", "opacity-0");
    window.setTimeout(() => item.remove(), EXIT_DURATION_MS);
  }

  function pauseDismissal(item) {
    const state = messageStates.get(item);
    if (!state || !state.timeoutId) {
      return;
    }

    window.clearTimeout(state.timeoutId);
    state.timeoutId = null;
    state.remaining = Math.max(0, state.remaining - (Date.now() - state.startedAt));
  }

  function resumeDismissal(item) {
    const state = messageStates.get(item);
    if (!state || state.timeoutId || item.matches(":hover, :focus-within")) {
      return;
    }

    if (state.remaining <= 0) {
      hideMessage(item);
      return;
    }

    state.startedAt = Date.now();
    state.timeoutId = window.setTimeout(() => hideMessage(item), state.remaining);
  }

  function initializeMessage(item) {
    if (messageStates.has(item)) {
      return;
    }

    const dismissButton = item.querySelector("[data-message-dismiss]");
    if (dismissButton) {
      dismissButton.addEventListener("click", (event) => {
        event.preventDefault();
        hideMessage(item);
      });
    }

    if (!shouldAutoDismiss(item)) {
      return;
    }

    const state = {
      abortController: new AbortController(),
      remaining: timeoutFor(item),
      startedAt: 0,
      timeoutId: null,
    };
    messageStates.set(item, state);

    item.addEventListener("mouseenter", () => pauseDismissal(item), {
      signal: state.abortController.signal,
    });
    item.addEventListener("focusin", () => pauseDismissal(item), {
      signal: state.abortController.signal,
    });
    item.addEventListener("mouseleave", () => resumeDismissal(item), {
      signal: state.abortController.signal,
    });
    item.addEventListener("focusout", () => resumeDismissal(item), {
      signal: state.abortController.signal,
    });

    resumeDismissal(item);
  }

  function initializeMessages(root = document) {
    root.querySelectorAll?.("[data-message-item]").forEach(initializeMessage);
  }

  const messageTypes = {
    error: {
      autoDismiss: false,
      buttonClasses: ["text-red-700", "hover:bg-red-100", "dark:text-red-200", "dark:hover:bg-red-900/60"],
      iconClasses: ["text-red-600", "dark:text-red-300"],
      path: "M10 18a8 8 0 100-16 8 8 0 000 16Zm-1-5a1 1 0 112 0 1 1 0 01-2 0Zm.25-7.25a.75.75 0 011.5 0v4.5a.75.75 0 01-1.5 0v-4.5Z",
      role: "alert",
      toneClasses: ["border-red-200", "bg-red-50", "text-red-900", "dark:border-red-900/60", "dark:bg-red-950", "dark:text-red-100"],
    },
    info: {
      autoDismiss: true,
      buttonClasses: ["text-sky-700", "hover:bg-sky-100", "dark:text-sky-200", "dark:hover:bg-sky-900/60"],
      iconClasses: ["text-sky-600", "dark:text-sky-300"],
      path: "M10 18a8 8 0 100-16 8 8 0 000 16Zm0-11.25a.75.75 0 110-1.5.75.75 0 010 1.5Zm-.75 2.5a.75.75 0 011.5 0v4a.75.75 0 01-1.5 0v-4Z",
      role: "status",
      toneClasses: ["border-sky-200", "bg-sky-50", "text-sky-950", "dark:border-sky-900/60", "dark:bg-sky-950", "dark:text-sky-100"],
    },
    success: {
      autoDismiss: true,
      buttonClasses: ["text-emerald-700", "hover:bg-emerald-100", "dark:text-emerald-200", "dark:hover:bg-emerald-900/60"],
      iconClasses: ["text-emerald-600", "dark:text-emerald-300"],
      path: "M10 18a8 8 0 100-16 8 8 0 000 16Zm3.857-9.809a.75.75 0 00-1.214-.882l-3.236 4.45-1.55-1.55a.75.75 0 10-1.06 1.061l2.17 2.17a.75.75 0 001.137-.089l3.753-5.16Z",
      role: "status",
      toneClasses: ["border-emerald-200", "bg-emerald-50", "text-emerald-950", "dark:border-emerald-900/60", "dark:bg-emerald-950", "dark:text-emerald-100"],
    },
    warning: {
      autoDismiss: false,
      buttonClasses: ["text-amber-800", "hover:bg-amber-100", "dark:text-amber-100", "dark:hover:bg-amber-900/60"],
      iconClasses: ["text-amber-600", "dark:text-amber-300"],
      path: "M8.257 3.099c.765-1.36 2.72-1.36 3.486 0l6.518 11.59c.75 1.333-.213 2.986-1.743 2.986H3.482c-1.53 0-2.493-1.653-1.743-2.986l6.518-11.59ZM10 7a.75.75 0 00-.75.75v3.5a.75.75 0 001.5 0v-3.5A.75.75 0 0010 7Zm0 7a1 1 0 100-2 1 1 0 000 2Z",
      role: "status",
      toneClasses: ["border-amber-200", "bg-amber-50", "text-amber-950", "dark:border-amber-900/60", "dark:bg-amber-950", "dark:text-amber-100"],
    },
  };

  function createMessagesContainer() {
    const container = document.createElement("div");
    container.dataset.messagesContainer = "true";
    container.className = [
      "pointer-events-none",
      "fixed",
      "inset-x-4",
      "top-4",
      "z-50",
      "max-h-[calc(100vh-2rem)]",
      "space-y-3",
      "overflow-y-auto",
      "sm:left-auto",
      "sm:right-4",
      "sm:w-full",
      "sm:max-w-sm",
    ].join(" ");
    container.setAttribute("aria-label", "Notifications");
    document.body.appendChild(container);
    return container;
  }

  function createIcon(config) {
    const wrapper = document.createElement("div");
    wrapper.className = "mt-0.5 flex-shrink-0";
    wrapper.setAttribute("aria-hidden", "true");

    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("class", ["h-5", "w-5", ...config.iconClasses].join(" "));
    icon.setAttribute("viewBox", "0 0 20 20");
    icon.setAttribute("fill", "currentColor");

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("fill-rule", "evenodd");
    path.setAttribute("clip-rule", "evenodd");
    path.setAttribute("d", config.path);

    icon.appendChild(path);
    wrapper.appendChild(icon);
    return wrapper;
  }

  function createDismissButton(config) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.messageDismiss = "true";
    button.className = [
      "fb-focus",
      "inline-flex",
      "h-7",
      "w-7",
      "flex-shrink-0",
      "items-center",
      "justify-center",
      "rounded-full",
      ...config.buttonClasses,
    ].join(" ");
    button.setAttribute("aria-label", "Dismiss notification");

    const hiddenLabel = document.createElement("span");
    hiddenLabel.className = "sr-only";
    hiddenLabel.textContent = "Dismiss notification";

    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("class", "h-4 w-4");
    icon.setAttribute("fill", "none");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("stroke", "currentColor");
    icon.setAttribute("aria-hidden", "true");

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    path.setAttribute("stroke-width", "2");
    path.setAttribute("d", "M6 18L18 6M6 6l12 12");

    icon.appendChild(path);
    button.append(hiddenLabel, icon);
    return button;
  }

  function createMessageElement(message, config, options) {
    const item = document.createElement("div");
    item.dataset.messageItem = "true";
    item.dataset.messageAutoDismiss = String(options.autoDismiss ?? config.autoDismiss);
    item.dataset.messageTimeout = String(options.timeout || DEFAULT_TIMEOUT_MS);
    item.setAttribute("role", config.role);
    item.setAttribute("aria-live", config.role === "alert" ? "assertive" : "polite");
    item.setAttribute("aria-atomic", "true");
    item.className = [
      "pointer-events-auto",
      "rounded-lg",
      "border",
      "p-4",
      "transition",
      "duration-200",
      "ease-out",
      "motion-reduce:transition-none",
      ...config.toneClasses,
    ].join(" ");

    const row = document.createElement("div");
    row.className = "flex items-start gap-3";

    const text = document.createElement("p");
    text.className = "min-w-0 flex-1 break-words text-sm leading-6";
    text.textContent = message;

    row.append(createIcon(config), text, createDismissButton(config));
    item.appendChild(row);
    return item;
  }

  Rowset.showMessage = function showMessage(message, type = "error", options = {}) {
    const normalizedType = String(type || "").toLowerCase();
    const config = messageTypes[normalizedType] || messageTypes.info;
    const container = document.querySelector("[data-messages-container]") || createMessagesContainer();
    const item = createMessageElement(String(message || "Notification"), config, options || {});

    container.appendChild(item);
    initializeMessage(item);
    return item;
  };

  function enhanceDocsCodeBlocks(root = document) {
    root.querySelectorAll?.(".docs-code-blocks pre").forEach((block) => {
      if (block.dataset.copyEnhanced === "true") {
        return;
      }

      const code = block.querySelector("code");
      if (!code) {
        return;
      }

      block.dataset.copyEnhanced = "true";
      const wrapper = document.createElement("div");
      wrapper.className = "group relative my-6";
      block.parentNode.insertBefore(wrapper, block);
      wrapper.appendChild(block);

      const button = document.createElement("button");
      button.type = "button";
      button.className =
        "absolute right-3 top-3 rounded-lg border border-slate-700 bg-slate-900/90 px-2.5 py-1 text-xs font-semibold text-slate-200 opacity-0 shadow-sm transition hover:bg-slate-800 focus:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 group-hover:opacity-100";
      button.textContent = "Copy";
      button.addEventListener("click", async () => {
        const copied = await Rowset.copyTextToClipboard?.(code.textContent);
        const original = button.dataset.originalLabel || button.textContent;
        button.dataset.originalLabel = original;
        button.textContent = copied ? "Copied" : "Copy failed";
        window.clearTimeout(Number(button.dataset.resetTimer));
        button.dataset.resetTimer = window.setTimeout(() => {
          button.textContent = original;
        }, 1600);
      });
      wrapper.appendChild(button);
    });
  }

  onReady(() => {
    configureHtmx();
    initializeMessages();
    enhanceDocsCodeBlocks();
    fetchUserSettings();
  });

  document.body?.addEventListener("htmx:afterSwap", (event) => {
    initializeAlpineTree(event.target);
    initializeMessages(event.target);
    enhanceDocsCodeBlocks(event.target);
  });
})();
