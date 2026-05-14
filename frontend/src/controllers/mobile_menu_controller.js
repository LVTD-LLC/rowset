import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["button", "menu"];

  connect() {
    this.close = this.close.bind(this);
    this.closeOnEscape = this.closeOnEscape.bind(this);
    document.addEventListener("keydown", this.closeOnEscape);
  }

  disconnect() {
    document.removeEventListener("keydown", this.closeOnEscape);
  }

  toggle(event) {
    event.preventDefault();
    event.stopPropagation();

    if (this.menuTarget.classList.contains("hidden")) {
      this.open();
    } else {
      this.close();
    }
  }

  open() {
    this.menuTarget.classList.remove("hidden");
    this.buttonTarget.setAttribute("aria-expanded", "true");
  }

  close() {
    this.menuTarget.classList.add("hidden");
    this.buttonTarget.setAttribute("aria-expanded", "false");
  }

  closeOnEscape(event) {
    if (
      event.key !== "Escape" ||
      this.menuTarget.classList.contains("hidden")
    ) {
      return;
    }

    this.close();
    this.buttonTarget.focus();
  }
}
