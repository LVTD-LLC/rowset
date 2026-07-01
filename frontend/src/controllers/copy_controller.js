import { Controller } from "@hotwired/stimulus";
import { copyTextToClipboard } from "../utils/clipboard";

export default class extends Controller {
  static targets = ["source", "label"];
  static values = { url: String, responseKey: String, trackingEvent: String };

  async copy(event) {
    event.preventDefault();

    const text = await this.getCopyText();
    if (!text) {
      if (this.hasLabelTarget) {
        this.flashLabel("Copy failed");
      }
      return;
    }

    const copied = await this.copyText(text);
    if (this.hasLabelTarget) {
      this.flashLabel(copied ? "Copied" : "Copy failed");
    }
    if (copied) {
      this.trackCopy();
    }
  }

  copyText(text) {
    const sourceElement = this.hasUrlValue && this.urlValue ? null : this.sourceTarget;
    return copyTextToClipboard(text, { sourceElement });
  }

  async getCopyText() {
    if (!this.hasUrlValue || !this.urlValue) {
      return this.sourceTarget.value || this.sourceTarget.textContent;
    }

    try {
      const response = await fetch(this.urlValue, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        return "";
      }

      const payload = await response.json();
      if (this.hasResponseKeyValue && this.responseKeyValue) {
        const value = payload[this.responseKeyValue];
        return typeof value === "string" ? value : "";
      }
      return payload.prompt || payload.api_key || payload.text || "";
    } catch (error) {
      return "";
    }
  }

  flashLabel(message) {
    const originalLabel = this.labelTarget.textContent;
    this.labelTarget.textContent = message;
    window.setTimeout(() => {
      this.labelTarget.textContent = originalLabel;
    }, 1600);
  }

  trackCopy() {
    if (!this.hasTrackingEventValue || !this.trackingEventValue) {
      return;
    }
    if (!window.posthog || typeof window.posthog.capture !== "function") {
      return;
    }

    const properties = {
      copy_source: this.hasUrlValue && this.urlValue ? "endpoint" : "inline",
      path: window.location.pathname,
    };
    if (this.hasResponseKeyValue && this.responseKeyValue) {
      properties.response_key = this.responseKeyValue;
    }

    window.posthog.capture(this.trackingEventValue, properties);
  }
}
