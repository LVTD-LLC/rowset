import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = ["badge", "message"];
  static values = { url: String, status: String };

  connect() {
    if (this.statusValue === "processing") {
      this.poll();
    }
  }

  async poll() {
    try {
      const response = await fetch(this.urlValue, { credentials: "same-origin" });
      const data = await response.json();
      this.badgeTarget.textContent = data.status;
      if (this.hasMessageTarget) {
        this.messageTarget.textContent = data.status === "ready"
          ? `${data.row_count.toLocaleString()} rows imported. Your API is ready.`
          : data.status === "failed"
            ? data.parse_error
            : "Still importing rows…";
      }
      if (data.status === "processing") {
        window.setTimeout(() => this.poll(), 2500);
      } else if (data.status === "ready") {
        window.setTimeout(() => window.location.reload(), 800);
      }
    } catch (_error) {
      window.setTimeout(() => this.poll(), 5000);
    }
  }
}
