import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["dialog"];

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
    this.element.querySelector("button")?.focus();
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
    }
  }
}
