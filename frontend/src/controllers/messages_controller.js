import { Controller } from "@hotwired/stimulus";

const DEFAULT_TIMEOUT_MS = 8000;
const EXIT_DURATION_MS = 200;

export default class extends Controller {
  static targets = ["item"];

  initialize() {
    this.dismissals = new Map();
  }

  disconnect() {
    this.dismissals.forEach((state) => this.clearDismissal(state));
    this.dismissals.clear();
  }

  itemTargetConnected(item) {
    if (this.dismissals.has(item)) return;

    item.dataset.messagesInitialized = "true";

    if (this.shouldAutoDismiss(item)) {
      this.scheduleDismissal(item);
    }
  }

  itemTargetDisconnected(item) {
    const state = this.dismissals.get(item);
    if (!state) return;

    this.clearDismissal(state);
    this.dismissals.delete(item);
  }

  dismiss(event) {
    event.preventDefault();

    const item = event.currentTarget.closest('[data-messages-target="item"]');
    if (item) {
      this.hide(item);
    }
  }

  scheduleDismissal(item) {
    const state = {
      abortController: new AbortController(),
      remaining: this.timeoutFor(item),
      startedAt: 0,
      timeoutId: null,
    };

    this.dismissals.set(item, state);
    item.addEventListener("mouseenter", () => this.pauseDismissal(item), {
      signal: state.abortController.signal,
    });
    item.addEventListener("focusin", () => this.pauseDismissal(item), {
      signal: state.abortController.signal,
    });
    item.addEventListener("mouseleave", () => this.resumeDismissal(item), {
      signal: state.abortController.signal,
    });
    item.addEventListener("focusout", () => this.resumeDismissal(item), {
      signal: state.abortController.signal,
    });

    this.resumeDismissal(item);
  }

  pauseDismissal(item) {
    const state = this.dismissals.get(item);
    if (!state || !state.timeoutId) return;

    window.clearTimeout(state.timeoutId);
    state.timeoutId = null;
    state.remaining = Math.max(0, state.remaining - (Date.now() - state.startedAt));
  }

  resumeDismissal(item) {
    const state = this.dismissals.get(item);
    if (!state || state.timeoutId || item.matches(":hover, :focus-within")) return;

    if (state.remaining <= 0) {
      this.hide(item);
      return;
    }

    state.startedAt = Date.now();
    state.timeoutId = window.setTimeout(() => this.hide(item), state.remaining);
  }

  hide(item) {
    const state = this.dismissals.get(item);
    if (state) {
      this.clearDismissal(state);
      this.dismissals.delete(item);
    }

    item.setAttribute("aria-hidden", "true");

    if (this.prefersReducedMotion()) {
      item.remove();
      return;
    }

    item.classList.add("translate-x-full", "opacity-0");
    window.setTimeout(() => {
      item.remove();
    }, EXIT_DURATION_MS);
  }

  clearDismissal(state) {
    if (state.timeoutId) {
      window.clearTimeout(state.timeoutId);
      state.timeoutId = null;
    }

    state.abortController.abort();
  }

  shouldAutoDismiss(item) {
    return item.dataset.messagesAutoDismiss !== "false" && item.getAttribute("role") !== "alert";
  }

  timeoutFor(item) {
    const timeout = Number.parseInt(item.dataset.messagesTimeout || "", 10);
    return Number.isFinite(timeout) && timeout > 0 ? timeout : DEFAULT_TIMEOUT_MS;
  }

  prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }
}
