import { Controller } from "@hotwired/stimulus";

export default class extends Controller {
  static targets = [
    "file",
    "googleSheetsUrl",
    "submit",
    "status",
    "preview",
    "headers",
    "sample",
    "rowCount",
    "indexSelector",
    "columnTypes",
    "columnType",
    "confirmForm",
  ];

  async preview(event) {
    event.preventDefault();

    const googleSheetsUrl = this.hasGoogleSheetsUrlTarget ? this.googleSheetsUrlTarget.value.trim() : "";
    const hasFile = this.hasFileTarget && this.fileTarget.files.length > 0;

    if (!hasFile && !googleSheetsUrl) {
      this.showError("Choose a CSV/Parquet file or paste a Google Sheets link first.");
      return;
    }

    this._submitLabel = this.submitTarget.textContent;
    this.submitTarget.disabled = true;
    this.submitTarget.textContent = "Reading preview…";
    this.statusTarget.textContent = "Reading dataset preview…";
    this.statusTarget.className = "text-sm text-gray-600 dark:text-gray-300";
    this.previewTarget.classList.add("hidden");

    const formData = new FormData();
    if (googleSheetsUrl) {
      formData.append("google_sheets_url", googleSheetsUrl);
    } else {
      formData.append("file", this.fileTarget.files[0]);
    }

    try {
      const response = await fetch(this.element.action, {
        method: "POST",
        body: formData,
        headers: { "X-CSRFToken": this.csrfToken },
        credentials: "same-origin",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Could not preview this file.");
      }
      this.renderPreview(payload.dataset);
    } catch (error) {
      this.showError(error.message);
    } finally {
      this.submitTarget.disabled = false;
      this.submitTarget.textContent = this._submitLabel ?? "Preview dataset";
    }
  }

  async confirm(event) {
    event.preventDefault();
    if (!this.confirmUrl) return;

    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Checking index…";
    this.statusTarget.textContent = "Checking index uniqueness…";
    this.statusTarget.className = "text-sm text-gray-600 dark:text-gray-300";

    const formData = new FormData();
    formData.append("index_column", this.indexSelectorTarget.value);
    formData.append("column_types", JSON.stringify(this.selectedColumnTypes));

    try {
      const response = await fetch(this.confirmUrl, {
        method: "POST",
        body: formData,
        headers: { "X-CSRFToken": this.csrfToken },
        credentials: "same-origin",
        redirect: "follow",
      });

      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.error || "Could not confirm this import.");
      }

      window.location.href = response.url;
    } catch (error) {
      this.showError(error.message);
      button.disabled = false;
      button.textContent = "Confirm import";
    }
  }

  renderPreview(dataset) {
    this.confirmUrl = dataset.confirm_url;
    this.statusTarget.textContent = "Preview ready. Choose a unique index, then confirm import.";
    this.statusTarget.className = "text-sm text-emerald-700 dark:text-emerald-300";
    this.rowCountTarget.textContent = `${dataset.row_count.toLocaleString()} rows detected`;
    this.headersTarget.innerHTML = dataset.headers
      .map((header) => `<span class="max-w-full break-words rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-800 dark:bg-slate-800 dark:text-slate-100">${this.escape(header)}</span>`)
      .join("");

    this.indexSelectorTarget.innerHTML = this.renderIndexOptions(dataset);
    this.columnTypesTarget.innerHTML = this.renderColumnTypeControls(dataset);

    const headerCells = dataset.headers.map((header) => `<th scope="col" class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">${this.escape(header)}</th>`).join("");
    const rows = dataset.preview_rows.map((row) => {
      const cells = dataset.headers.map((header) => `<td class="max-w-xs truncate px-3 py-2 text-sm text-slate-700 dark:text-slate-200">${this.escape(row[header] || "")}</td>`).join("");
      return `<tr class="border-t border-slate-100 dark:border-slate-800">${cells}</tr>`;
    }).join("");

    this.sampleTarget.innerHTML = `<table class="min-w-full divide-y divide-slate-200 dark:divide-slate-800" aria-label="Dataset preview"><thead><tr>${headerCells}</tr></thead><tbody>${rows}</tbody></table>`;
    this.confirmFormTarget.innerHTML = '<button type="button" data-action="csv-upload#confirm" class="fb-button-primary">Confirm import</button>';
    this.previewTarget.classList.remove("hidden");
  }

  renderIndexOptions(dataset) {
    const generated = `<option value="${this.escape(dataset.generated_index_choice)}">Generate a FileBridge ID column</option>`;
    const headers = dataset.headers
      .map((header) => `<option value="${this.escape(header)}">${this.escape(header)}</option>`)
      .join("");
    return `${generated}${headers}`;
  }

  renderColumnTypeControls(dataset) {
    const options = dataset.column_type_options || [
      { value: "text", label: "Text" },
      { value: "integer", label: "Integer" },
      { value: "number", label: "Number" },
      { value: "currency", label: "Currency" },
      { value: "boolean", label: "Boolean" },
      { value: "date", label: "Date" },
      { value: "datetime", label: "Date/time" },
      { value: "email", label: "Email" },
      { value: "url", label: "URL" },
    ];
    const schema = dataset.column_schema || {};
    const controls = dataset.headers.map((header) => {
      const selectedType = schema[header]?.type || "text";
      const optionHtml = options.map((option) => {
        const selected = option.value === selectedType ? " selected" : "";
        return `<option value="${this.escape(option.value)}"${selected}>${this.escape(option.label)}</option>`;
      }).join("");
      return `
        <label class="grid gap-1 text-sm sm:grid-cols-[minmax(0,1fr)_12rem] sm:items-center">
          <span class="min-w-0 break-words font-semibold text-slate-700 dark:text-slate-200">${this.escape(header)}</span>
          <select data-csv-upload-target="columnType" data-column-name="${this.escape(header)}" class="fb-input w-full px-3 py-2 text-sm">
            ${optionHtml}
          </select>
        </label>
      `;
    }).join("");

    return `
      <div>
        <p class="mb-2 text-sm font-semibold text-slate-900 dark:text-slate-100">Column types</p>
        <div class="grid gap-3 sm:max-w-2xl">${controls}</div>
      </div>
    `;
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

  get selectedColumnTypes() {
    if (!this.hasColumnTypeTarget) return {};
    return this.columnTypeTargets.reduce((columnTypes, select) => {
      columnTypes[select.dataset.columnName] = select.value;
      return columnTypes;
    }, {});
  }

  get csrfToken() {
    return document.cookie
      .split("; ")
      .find((row) => row.startsWith("csrftoken="))
      ?.split("=")[1];
  }
}
