import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["descriptionInput", "display", "editButton", "error", "form", "nameInput"];
  static values = { description: String, name: String };

  edit(event) {
    event.preventDefault();
    this.showForm();
  }

  cancel(event) {
    event.preventDefault();
    this.restoreSavedValues();
    this.clearServerError();
    this.showDisplay();
  }

  showForm() {
    this.displayTarget.classList.add("hidden");
    this.formTarget.classList.remove("hidden");

    if (this.hasEditButtonTarget) {
      this.editButtonTarget.classList.add("hidden");
    }

    if (this.hasNameInputTarget) {
      this.nameInputTarget.focus();
      this.nameInputTarget.select();
    }
  }

  showDisplay() {
    this.formTarget.classList.add("hidden");
    this.displayTarget.classList.remove("hidden");

    if (this.hasEditButtonTarget) {
      this.editButtonTarget.classList.remove("hidden");
      this.editButtonTarget.focus();
    }
  }

  clearServerError() {
    if (this.hasErrorTarget) {
      this.errorTarget.remove();
    }

    if (this.hasNameInputTarget) {
      this.nameInputTarget.removeAttribute("aria-describedby");
      this.nameInputTarget.removeAttribute("aria-invalid");
    }
  }

  restoreSavedValues() {
    if (this.hasNameInputTarget) {
      this.nameInputTarget.value = this.nameValue || "";
    }

    if (this.hasDescriptionInputTarget) {
      this.descriptionInputTarget.value = this.descriptionValue || "";
    }
  }
}
