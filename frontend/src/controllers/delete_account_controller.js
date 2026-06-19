import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["modal", "panel", "confirmation", "submit"];

  connect() {
    this.handleKeydown = this.handleKeydown.bind(this);
    this.returnFocusElement = null;
    this.previousBodyOverflow = "";
  }

  disconnect() {
    document.removeEventListener("keydown", this.handleKeydown);
    if (this.hasModalTarget && !this.modalTarget.classList.contains("hidden")) {
      document.body.style.overflow = this.previousBodyOverflow;
    }
  }

  open(event) {
    if (!this.hasModalTarget) return;
    document.removeEventListener("keydown", this.handleKeydown);

    this.returnFocusElement = event?.currentTarget || document.activeElement;
    this.previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    this.modalTarget.classList.remove("hidden");
    this.modalTarget.classList.add("flex");
    this.modalTarget.setAttribute("aria-hidden", "false");

    if (this.hasConfirmationTarget) {
      this.confirmationTarget.value = "";
    }

    this.update();
    document.addEventListener("keydown", this.handleKeydown);

    window.requestAnimationFrame(() => {
      this.confirmationTarget?.focus();
    });
  }

  close() {
    if (!this.hasModalTarget) return;

    this.modalTarget.classList.add("hidden");
    this.modalTarget.classList.remove("flex");
    this.modalTarget.setAttribute("aria-hidden", "true");
    document.body.style.overflow = this.previousBodyOverflow;
    document.removeEventListener("keydown", this.handleKeydown);

    if (
      this.returnFocusElement &&
      document.contains(this.returnFocusElement) &&
      typeof this.returnFocusElement.focus === "function"
    ) {
      this.returnFocusElement.focus();
    }
  }

  update() {
    if (!this.hasSubmitTarget || !this.hasConfirmationTarget) return;

    const isConfirmed = this.confirmationTarget.value === "DELETE";
    this.submitTarget.disabled = !isConfirmed;
    this.submitTarget.setAttribute("aria-disabled", String(!isConfirmed));
  }

  submit(event) {
    if (!this.hasSubmitTarget || !this.hasConfirmationTarget) return;

    if (this.confirmationTarget.value !== "DELETE") {
      event.preventDefault();
      this.confirmationTarget.focus();
      return;
    }

    this.submitTarget.disabled = true;
    this.submitTarget.setAttribute("aria-disabled", "true");
    this.submitTarget.textContent = "Deleting...";
  }

  handleKeydown(event) {
    if (this.modalTarget.classList.contains("hidden")) return;

    if (event.key === "Escape") {
      event.preventDefault();
      this.close();
      return;
    }

    if (event.key === "Tab") {
      this.trapFocus(event);
    }
  }

  trapFocus(event) {
    const focusableElements = this.focusableElements();
    if (focusableElements.length === 0) {
      event.preventDefault();
      return;
    }

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    if (!this.panelTarget.contains(document.activeElement)) {
      event.preventDefault();
      firstElement.focus();
    } else if (event.shiftKey && document.activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
    } else if (!event.shiftKey && document.activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  }

  focusableElements() {
    if (!this.hasPanelTarget) return [];

    const selectors = [
      "a[href]",
      "button:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    return Array.from(this.panelTarget.querySelectorAll(selectors)).filter((element) => {
      const style = window.getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden";
    });
  }
}
