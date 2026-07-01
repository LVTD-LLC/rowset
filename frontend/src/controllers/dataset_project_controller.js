import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["projectSelect", "sectionSelect"];

  connect() {
    this.syncSections();
  }

  syncSections() {
    const projectKey = this.projectSelectTarget.value;
    let selectedOptionIsValid = false;

    for (const option of this.sectionSelectTarget.options) {
      const optionProjectKey = option.dataset.projectKey || "";
      const optionIsBlank = option.value === "";
      const optionIsValid = optionIsBlank || (projectKey && optionProjectKey === projectKey);

      option.hidden = !optionIsValid;
      option.disabled = !optionIsValid;

      if (option.selected && optionIsValid) {
        selectedOptionIsValid = true;
      }
    }

    if (!projectKey || !selectedOptionIsValid) {
      this.sectionSelectTarget.value = "";
    }
  }
}
