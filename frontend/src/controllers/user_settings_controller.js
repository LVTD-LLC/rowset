import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  connect() {
    this.abortController = new AbortController();
    this.fetchAndStoreSettings();
  }

  disconnect() {
    this.abortController?.abort();
  }

  async fetchAndStoreSettings() {
    try {
      const response = await fetch(`/api/user/settings`, {
        signal: this.abortController.signal,
      });
      if (!response.ok) {
        return;
      }
      const data = await response.json();

      localStorage.setItem(`userSettings`, JSON.stringify(data));

    } catch (error) {
      if (error.name !== "AbortError") {
        return;
      }
    }
  }
}
