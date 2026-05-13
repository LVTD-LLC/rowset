import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = [
    "file",
    "submit",
    "status",
    "preview",
    "headers",
    "sample",
    "rowCount",
    "confirmForm",
  ];

  async preview(event) {
    event.preventDefault();

    if (!this.hasFileTarget || this.fileTarget.files.length === 0) {
      this.showError("Choose a CSV file first.");
      return;
    }

    this.submitTarget.disabled = true;
    this.statusTarget.textContent = "Reading CSV preview…";
    this.statusTarget.className = "text-sm text-gray-600 dark:text-gray-300";
    this.previewTarget.classList.add("hidden");

    const formData = new FormData();
    formData.append("file", this.fileTarget.files[0]);

    try {
      const response = await fetch(this.element.action, {
        method: "POST",
        body: formData,
        headers: { "X-CSRFToken": this.csrfToken },
        credentials: "same-origin",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Could not preview this CSV file.");
      }
      this.renderPreview(payload.dataset);
    } catch (error) {
      this.showError(error.message);
    } finally {
      this.submitTarget.disabled = false;
    }
  }

  async confirm(event) {
    event.preventDefault();
    if (!this.confirmUrl) return;

    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Starting import…";

    const response = await fetch(this.confirmUrl, {
      method: "POST",
      headers: { "X-CSRFToken": this.csrfToken },
      credentials: "same-origin",
      redirect: "follow",
    });
    window.location.href = response.url;
  }

  renderPreview(dataset) {
    this.confirmUrl = dataset.confirm_url;
    this.statusTarget.textContent = "Preview ready. Confirm it if the headers and sample rows look right.";
    this.statusTarget.className = "text-sm text-emerald-700 dark:text-emerald-300";
    this.rowCountTarget.textContent = `${dataset.row_count.toLocaleString()} rows detected`;
    this.headersTarget.innerHTML = dataset.headers
      .map((header) => `<span class="rounded-full bg-gray-100 px-3 py-1 text-sm font-medium text-gray-800 dark:bg-gray-800 dark:text-gray-100">${this.escape(header)}</span>`)
      .join("");

    const headerCells = dataset.headers.map((header) => `<th class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">${this.escape(header)}</th>`).join("");
    const rows = dataset.preview_rows.map((row) => {
      const cells = dataset.headers.map((header) => `<td class="max-w-xs truncate px-3 py-2 text-sm text-gray-700 dark:text-gray-200">${this.escape(row[header] || "")}</td>`).join("");
      return `<tr class="border-t border-gray-100 dark:border-gray-800">${cells}</tr>`;
    }).join("");

    this.sampleTarget.innerHTML = `<table class="min-w-full divide-y divide-gray-200 dark:divide-gray-800"><thead><tr>${headerCells}</tr></thead><tbody>${rows}</tbody></table>`;
    this.confirmFormTarget.innerHTML = '<button type="button" data-action="csv-upload#confirm" class="inline-flex justify-center rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 dark:focus:ring-offset-gray-900">Confirm import</button>';
    this.previewTarget.classList.remove("hidden");
  }

  showError(message) {
    this.statusTarget.textContent = message;
    this.statusTarget.className = "text-sm text-red-700 dark:text-red-300";
  }

  escape(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  get csrfToken() {
    return document.cookie
      .split("; ")
      .find((row) => row.startsWith("csrftoken="))
      ?.split("=")[1];
  }
}
