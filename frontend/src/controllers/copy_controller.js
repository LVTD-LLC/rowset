import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["source", "label"];

  async copy(event) {
    event.preventDefault();

    const text = this.sourceTarget.value || this.sourceTarget.textContent;
    if (!text) {
      return;
    }

    try {
      await navigator.clipboard.writeText(text);
    } catch (error) {
      this.sourceTarget.focus();
      this.sourceTarget.select();
      document.execCommand("copy");
    }

    if (this.hasLabelTarget) {
      const originalLabel = this.labelTarget.textContent;
      this.labelTarget.textContent = "Copied";
      window.setTimeout(() => {
        this.labelTarget.textContent = originalLabel;
      }, 1600);
    }
  }
}
