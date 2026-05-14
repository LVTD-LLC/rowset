import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["source", "label"];

  async copy(event) {
    event.preventDefault();

    const text = this.sourceTarget.value || this.sourceTarget.textContent;
    if (!text) {
      return;
    }

    const copied = await this.copyText(text);
    if (this.hasLabelTarget) {
      this.flashLabel(copied ? "Copied" : "Copy failed");
    }
  }

  async copyText(text) {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (error) {
        // Fall back for browsers/contexts where clipboard permissions are blocked.
      }
    }

    return this.copyWithSelectionFallback();
  }

  copyWithSelectionFallback() {
    this.sourceTarget.focus();
    this.sourceTarget.select();
    try {
      return document.execCommand("copy");
    } catch (error) {
      return false;
    }
  }

  flashLabel(message) {
    const originalLabel = this.labelTarget.textContent;
    this.labelTarget.textContent = message;
    window.setTimeout(() => {
      this.labelTarget.textContent = originalLabel;
    }, 1600);
  }
}
