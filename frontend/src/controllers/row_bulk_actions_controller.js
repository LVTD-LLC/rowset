import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["action", "checkbox", "count", "selectAll", "submit"];

  connect() {
    this.sync();
  }

  toggleAll() {
    if (!this.hasSelectAllTarget) {
      return;
    }

    this.checkboxTargets.forEach((checkbox) => {
      checkbox.checked = this.selectAllTarget.checked;
    });
    this.sync();
  }

  sync() {
    if (!this.hasCountTarget || !this.hasActionTarget || !this.hasSubmitTarget) {
      return;
    }

    const selectedCount = this.selectedCheckboxes.length;
    this.countTarget.textContent = selectedCount.toString();
    this.syncSelectAll(selectedCount);
    this.submitTarget.disabled = selectedCount === 0 || this.actionTarget.value === "";
  }

  confirm(event) {
    if (!this.hasActionTarget) {
      return;
    }

    if (this.actionTarget.value !== "delete") {
      return;
    }

    const selectedCount = this.selectedCheckboxes.length;
    if (selectedCount === 0) {
      event.preventDefault();
      return;
    }

    const rowLabel = selectedCount === 1 ? "row" : "rows";
    if (!window.confirm(`Delete ${selectedCount} selected ${rowLabel}? This cannot be undone.`)) {
      event.preventDefault();
    }
  }

  syncSelectAll(selectedCount) {
    if (!this.hasSelectAllTarget) {
      return;
    }

    this.selectAllTarget.checked =
      this.checkboxTargets.length > 0 && selectedCount === this.checkboxTargets.length;
    this.selectAllTarget.indeterminate =
      selectedCount > 0 && selectedCount < this.checkboxTargets.length;
  }

  get selectedCheckboxes() {
    return this.checkboxTargets.filter((checkbox) => checkbox.checked);
  }
}
