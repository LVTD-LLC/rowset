import { Controller } from "@hotwired/stimulus";

const POLL_INTERVAL_MS = 2500;
const RETRY_BASE_INTERVAL_MS = 5000;
const RETRY_MAX_INTERVAL_MS = 30000;
const READY_RELOAD_DELAY_MS = 800;

const STATUS_LABELS = {
  previewed: "Previewed",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
};

const BADGE_TONE_CLASSES = [
  "bg-amber-50",
  "text-amber-800",
  "dark:bg-amber-950/50",
  "dark:text-amber-200",
  "bg-emerald-50",
  "text-emerald-800",
  "dark:bg-emerald-950/50",
  "dark:text-emerald-200",
  "bg-red-50",
  "text-red-800",
  "dark:bg-red-950/50",
  "dark:text-red-200",
  "bg-slate-100",
  "text-slate-700",
  "dark:bg-slate-900",
  "dark:text-slate-300",
];

const BADGE_CLASSES_BY_STATUS = {
  processing: ["bg-amber-50", "text-amber-800", "dark:bg-amber-950/50", "dark:text-amber-200"],
  ready: ["bg-emerald-50", "text-emerald-800", "dark:bg-emerald-950/50", "dark:text-emerald-200"],
  failed: ["bg-red-50", "text-red-800", "dark:bg-red-950/50", "dark:text-red-200"],
  previewed: ["bg-slate-100", "text-slate-700", "dark:bg-slate-900", "dark:text-slate-300"],
};

const MESSAGE_TONE_CLASSES = [
  "text-slate-600",
  "dark:text-slate-300",
  "text-emerald-700",
  "dark:text-emerald-300",
  "text-red-700",
  "dark:text-red-300",
];

const MESSAGE_CLASSES_BY_STATUS = {
  ready: ["text-emerald-700", "dark:text-emerald-300"],
  failed: ["text-red-700", "dark:text-red-300"],
  processing: ["text-slate-600", "dark:text-slate-300"],
  previewed: ["text-slate-600", "dark:text-slate-300"],
};

export default class extends Controller {
  static targets = ["badge", "message"];
  static values = { url: String, status: String };

  connect() {
    this.retryCount = 0;
    this.timeoutId = null;
    this.abortController = null;
    this.isActive = true;

    if (this.normalizeStatus(this.statusValue) === "processing") {
      this.poll();
    }
  }

  disconnect() {
    this.isActive = false;
    this.clearTimer();
    this.abortRequest();
  }

  async poll() {
    if (!this.isActive) {
      return;
    }

    if (!this.hasUrlValue || !this.urlValue) {
      this.showTerminalError("Status updates are unavailable. Refresh the page to check this dataset.");
      return;
    }

    this.abortController = new AbortController();

    try {
      const response = await fetch(this.urlValue, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: this.abortController.signal,
      });

      if (!this.isActive) {
        return;
      }

      if (response.redirected) {
        this.showTerminalError("Your session expired. Refresh the page and sign in again.");
        return;
      }

      if (!response.ok) {
        this.handleErrorResponse(response);
        return;
      }

      const data = await response.json();
      if (!this.isActive) {
        return;
      }

      const status = this.normalizeStatus(data.status);
      if (!status) {
        this.showRetryMessage("Status update returned an unexpected response. Retrying…");
        return;
      }

      this.retryCount = 0;
      this.updateStatus(status, data);
    } catch (error) {
      if (error.name !== "AbortError") {
        this.showRetryMessage("Status update is unavailable. Retrying…");
      }
    } finally {
      this.abortController = null;
    }
  }

  handleErrorResponse(response) {
    if (response.status === 401) {
      this.showTerminalError("Your session expired. Refresh the page and sign in again.");
      return;
    }

    if (response.status === 403) {
      this.showTerminalError("You no longer have access to this dataset status.");
      return;
    }

    if (response.status === 404) {
      this.showTerminalError("This dataset is no longer available. Return to datasets and refresh the list.");
      return;
    }

    if (response.status === 429) {
      this.showRetryMessage("Status checks are being rate limited. Retrying…");
      return;
    }

    this.showRetryMessage("Status update is unavailable. Retrying…");
  }

  updateStatus(status, data) {
    this.statusValue = status;
    this.updateBadge(status);
    this.setMessage(this.messageForStatus(status, data), status);

    if (status === "processing") {
      this.schedulePoll(POLL_INTERVAL_MS);
    } else if (status === "ready") {
      this.scheduleReload();
    }
  }

  updateBadge(status) {
    if (!this.hasBadgeTarget) {
      return;
    }

    const label = STATUS_LABELS[status];
    this.badgeTarget.textContent = label;
    this.badgeTarget.setAttribute("aria-label", `Dataset status: ${label}`);
    this.badgeTarget.classList.remove(...BADGE_TONE_CLASSES);
    this.badgeTarget.classList.add(...(BADGE_CLASSES_BY_STATUS[status] || BADGE_CLASSES_BY_STATUS.previewed));
  }

  messageForStatus(status, data) {
    if (status === "ready") {
      return `${this.formatRowCount(data.row_count)} rows imported. Your API is ready.`;
    }

    if (status === "failed") {
      return data.parse_error || "Import failed. Check the source data and try again.";
    }

    if (status === "previewed") {
      return "Previewed. Confirm import to create API rows.";
    }

    return "Still importing rows…";
  }

  setMessage(message, status) {
    if (!this.hasMessageTarget) {
      return;
    }

    this.messageTarget.textContent = message;
    this.messageTarget.setAttribute("role", status === "failed" ? "alert" : "status");
    this.messageTarget.setAttribute("aria-live", status === "failed" ? "assertive" : "polite");
    this.messageTarget.setAttribute("aria-atomic", "true");
    this.messageTarget.classList.remove(...MESSAGE_TONE_CLASSES);
    this.messageTarget.classList.add(...(MESSAGE_CLASSES_BY_STATUS[status] || MESSAGE_CLASSES_BY_STATUS.processing));
  }

  showRetryMessage(message) {
    if (!this.isActive) {
      return;
    }

    this.setMessage(message, "processing");
    this.retryCount += 1;
    const delay = Math.min(RETRY_BASE_INTERVAL_MS * (2 ** (this.retryCount - 1)), RETRY_MAX_INTERVAL_MS);
    this.schedulePoll(delay);
  }

  showTerminalError(message) {
    this.clearTimer();
    this.abortRequest();
    this.setMessage(message, "failed");
  }

  schedulePoll(delay) {
    this.clearTimer();

    if (!this.isActive) {
      return;
    }

    this.timeoutId = window.setTimeout(() => this.poll(), delay);
  }

  scheduleReload() {
    this.clearTimer();

    if (!this.isActive) {
      return;
    }

    this.timeoutId = window.setTimeout(() => {
      window.location.reload();
    }, READY_RELOAD_DELAY_MS);
  }

  clearTimer() {
    if (this.timeoutId) {
      window.clearTimeout(this.timeoutId);
      this.timeoutId = null;
    }
  }

  abortRequest() {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
  }

  normalizeStatus(status) {
    const normalized = String(status || "").toLowerCase();
    return Object.prototype.hasOwnProperty.call(STATUS_LABELS, normalized) ? normalized : "";
  }

  formatRowCount(rowCount) {
    const count = Number(rowCount);
    if (!Number.isFinite(count)) {
      return "0";
    }

    return new Intl.NumberFormat(document.documentElement.lang || undefined).format(count);
  }
}
