import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["actions", "display", "input", "inputWrapper"];

  connect() {
    this.syncActions();
  }

  edit(event) {
    const field = event.currentTarget.closest("[data-row-inline-edit-field]");
    const display = field?.querySelector("[data-row-inline-edit-target~='display']");
    const wrapper = field?.querySelector("[data-row-inline-edit-target~='inputWrapper']");
    const input = field?.querySelector("[data-row-inline-edit-target~='input']");

    if (!field || !display || !wrapper || !input) {
      return;
    }

    display.classList.add("hidden");
    wrapper.classList.remove("hidden");
    input.disabled = false;
    if (input.value === "") {
      input.value = input.dataset.originalValue || "";
    }
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    this.syncActions();
  }

  cancel() {
    this.inputTargets.forEach((input) => {
      input.value = input.dataset.originalValue || "";
      input.disabled = true;
    });
    this.displayTargets.forEach((display) => display.classList.remove("hidden"));
    this.inputWrapperTargets.forEach((wrapper) => wrapper.classList.add("hidden"));
    this.syncActions();
  }

  syncActions() {
    const hasOpenInput = this.inputTargets.some((input) => !input.disabled);
    this.actionsTarget.classList.toggle("hidden", !hasOpenInput);
  }
}
