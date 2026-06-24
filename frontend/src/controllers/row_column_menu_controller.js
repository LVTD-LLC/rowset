import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["dialog"];

  connect() {
    this.repositionFrame = null;
    this.returnFocus = this.returnFocus.bind(this);
    this.repositionDialog = this.repositionDialog.bind(this);
    this.scheduleRepositionDialog = this.scheduleRepositionDialog.bind(this);
    this.dialogTarget.addEventListener("close", this.returnFocus);
  }

  disconnect() {
    this.dialogTarget.removeEventListener("close", this.returnFocus);
    this.removePositionListeners();
  }

  open(event) {
    event.preventDefault();
    this.triggerElement = event.currentTarget;

    if (this.dialogTarget.open) {
      this.positionDialog(this.triggerElement);
      return;
    }

    if (typeof this.dialogTarget.showModal === "function") {
      this.dialogTarget.showModal();
    } else {
      this.dialogTarget.setAttribute("open", "");
    }

    this.positionDialog(this.triggerElement);
    this.addPositionListeners();
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
    this.removePositionListeners();
    this.triggerElement?.focus();
    this.triggerElement = null;
  }

  positionDialog(triggerElement) {
    if (!triggerElement) {
      return;
    }

    const viewportPadding = 16;
    const triggerGap = 6;
    const triggerRect = triggerElement.getBoundingClientRect();
    const dialogRect = this.dialogTarget.getBoundingClientRect();
    const maxLeft = window.innerWidth - dialogRect.width - viewportPadding;
    const preferredTop = triggerRect.bottom + triggerGap;
    const maxTop = window.innerHeight - dialogRect.height - viewportPadding;
    const canOpenAbove = triggerRect.top - dialogRect.height - triggerGap >= viewportPadding;
    const top =
      preferredTop <= maxTop || !canOpenAbove
        ? Math.min(Math.max(preferredTop, viewportPadding), Math.max(maxTop, viewportPadding))
        : triggerRect.top - dialogRect.height - triggerGap;
    const left = Math.min(
      Math.max(triggerRect.left, viewportPadding),
      Math.max(maxLeft, viewportPadding)
    );

    Object.assign(this.dialogTarget.style, {
      inset: "auto",
      left: `${Math.round(left)}px`,
      margin: "0",
      position: "fixed",
      top: `${Math.round(top)}px`,
    });
  }

  repositionDialog() {
    this.repositionFrame = null;

    if (!this.dialogTarget.open) {
      return;
    }

    this.positionDialog(this.triggerElement);
  }

  scheduleRepositionDialog() {
    if (this.repositionFrame !== null) {
      return;
    }

    this.repositionFrame = window.requestAnimationFrame(this.repositionDialog);
  }

  addPositionListeners() {
    window.addEventListener("resize", this.scheduleRepositionDialog);
    window.addEventListener("scroll", this.scheduleRepositionDialog, true);
  }

  removePositionListeners() {
    window.removeEventListener("resize", this.scheduleRepositionDialog);
    window.removeEventListener("scroll", this.scheduleRepositionDialog, true);
    this.cancelScheduledReposition();
  }

  cancelScheduledReposition() {
    if (this.repositionFrame === null) {
      return;
    }

    window.cancelAnimationFrame(this.repositionFrame);
    this.repositionFrame = null;
  }
}
