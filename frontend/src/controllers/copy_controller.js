import { Controller } from "@hotwired/stimulus";
import { copyTextToClipboard } from "../utils/clipboard";

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

  copyText(text) {
    return copyTextToClipboard(text, { sourceElement: this.sourceTarget });
  }

  flashLabel(message) {
    const originalLabel = this.labelTarget.textContent;
    this.labelTarget.textContent = message;
    window.setTimeout(() => {
      this.labelTarget.textContent = originalLabel;
    }, 1600);
  }
}
