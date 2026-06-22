import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  connect() {
    this.closeOnOutsideClick = this.closeOnOutsideClick.bind(this);
    this.closeOnOutsideFocus = this.closeOnOutsideFocus.bind(this);
    this.closeOnEscape = this.closeOnEscape.bind(this);

    document.addEventListener("click", this.closeOnOutsideClick);
    document.addEventListener("focusin", this.closeOnOutsideFocus);
    document.addEventListener("keydown", this.closeOnEscape);
  }

  disconnect() {
    document.removeEventListener("click", this.closeOnOutsideClick);
    document.removeEventListener("focusin", this.closeOnOutsideFocus);
    document.removeEventListener("keydown", this.closeOnEscape);
  }

  closeOnOutsideClick(event) {
    if (!this.isOpen() || this.element.contains(event.target)) {
      return;
    }

    this.close();
  }

  closeOnOutsideFocus(event) {
    if (!this.isOpen() || this.element.contains(event.target)) {
      return;
    }

    this.close();
  }

  closeOnEscape(event) {
    if (event.key !== "Escape" || !this.isOpen()) {
      return;
    }

    event.preventDefault();
    this.close();
    this.element.querySelector("summary")?.focus();
  }

  isOpen() {
    return this.element.open;
  }

  close() {
    this.element.open = false;
  }
}
