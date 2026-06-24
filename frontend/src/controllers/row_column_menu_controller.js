import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["dialog"];

  connect() {
    this.returnFocus = this.returnFocus.bind(this);
    this.dialogTarget.addEventListener("close", this.returnFocus);
  }

  disconnect() {
    this.dialogTarget.removeEventListener("close", this.returnFocus);
  }

  open(event) {
    event.preventDefault();

    if (this.dialogTarget.open) {
      return;
    }

    if (typeof this.dialogTarget.showModal === "function") {
      this.dialogTarget.showModal();
    } else {
      this.dialogTarget.setAttribute("open", "");
    }

    this.dialogTarget
      .querySelector("select, input:not([type='hidden']), button[type='submit']")
      ?.focus();
  }

  close(event) {
    event.preventDefault();
    this.closeDialog();
  }

  closeFromBackdrop(event) {
    if (event.target !== this.dialogTarget) {
      return;
    }

    this.closeDialog();
  }

  closeDialog() {
    if (typeof this.dialogTarget.close === "function") {
      this.dialogTarget.close();
    } else {
      this.dialogTarget.removeAttribute("open");
      this.returnFocus();
    }
  }

  returnFocus() {
    this.element.querySelector("button")?.focus();
  }
}
