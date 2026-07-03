(function () {
  const Rowset = (window.Rowset = window.Rowset || {});

  Rowset.copyTextToClipboard = async function copyTextToClipboard(text, { sourceElement } = {}) {
    if (!text) {
      return false;
    }

    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_error) {
        // Fall back when clipboard permissions are unavailable.
      }
    }

    if (sourceElement && typeof sourceElement.select === "function") {
      sourceElement.focus();
      sourceElement.select();
      try {
        return document.execCommand("copy");
      } catch (_error) {
        return false;
      }
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.top = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();

    try {
      return document.execCommand("copy");
    } catch (_error) {
      return false;
    } finally {
      textarea.remove();
    }
  };

  function csrfToken() {
    return document.body?.dataset.csrfToken || "";
  }

  async function parseJsonResponse(response) {
    try {
      return await response.json();
    } catch (_error) {
      return {};
    }
  }

  function focusableElements(container) {
    if (!container) {
      return [];
    }

    const selectors = [
      "a[href]",
      "button:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    return Array.from(container.querySelectorAll(selectors)).filter((element) => {
      const style = window.getComputedStyle(element);
      return style.display !== "none" && style.visibility !== "hidden";
    });
  }

  function positionDialog(dialog, triggerElement) {
    if (!dialog || !triggerElement) {
      return;
    }

    const viewportPadding = 16;
    const triggerGap = 6;
    const triggerRect = triggerElement.getBoundingClientRect();
    const dialogRect = dialog.getBoundingClientRect();
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
      Math.max(maxLeft, viewportPadding),
    );

    Object.assign(dialog.style, {
      inset: "auto",
      left: `${Math.round(left)}px`,
      margin: "0",
      position: "fixed",
      top: `${Math.round(top)}px`,
    });
  }

  document.addEventListener("alpine:init", () => {
    Alpine.data("copyPanel", () => ({
      busy: false,
      label: "Copy",
      resetTimer: null,

      init() {
        this.label =
          this.$el.dataset.copyLabel ||
          this.$refs.label?.textContent?.trim() ||
          "Copy";
      },

      async copy(event) {
        event.preventDefault();
        if (this.busy) {
          return;
        }

        this.busy = true;
        const text = await this.copyText();
        const copied = await Rowset.copyTextToClipboard(text, {
          sourceElement: this.$el.dataset.copyUrl ? null : this.$refs.source,
        });

        this.flashLabel(copied ? "Copied" : "Copy failed");
        this.trackCopy(copied);
        this.busy = false;
      },

      async copyText() {
        const url = this.$el.dataset.copyUrl || "";
        if (!url) {
          return this.$refs.source?.value || this.$refs.source?.textContent || "";
        }

        try {
          const response = await fetch(url, {
            credentials: "same-origin",
            headers: { Accept: "application/json" },
          });
          if (!response.ok) {
            return "";
          }

          const payload = await response.json();
          const responseKey = this.$el.dataset.copyResponseKey || "";
          if (responseKey) {
            return typeof payload[responseKey] === "string" ? payload[responseKey] : "";
          }
          return payload.prompt || payload.api_key || payload.text || "";
        } catch (_error) {
          return "";
        }
      },

      flashLabel(message) {
        window.clearTimeout(this.resetTimer);
        const originalLabel =
          this.$el.dataset.copyLabel ||
          this.$refs.label?.dataset.originalLabel ||
          this.label;
        if (this.$refs.label) {
          this.$refs.label.dataset.originalLabel = originalLabel;
        }

        this.label = message;
        this.resetTimer = window.setTimeout(() => {
          this.label = originalLabel;
        }, 1600);
      },

      trackCopy(copied) {
        const eventName = this.$el.dataset.copyTrackingEvent || "";
        if (!copied || !eventName || typeof window.posthog?.capture !== "function") {
          return;
        }

        window.posthog.capture(eventName);
      },
    }));

    Alpine.data("commandPalette", () => ({
      activeIndex: -1,
      activeResultId: "",
      afterSwapHandler: null,
      open: false,
      previousBodyOverflow: "",
      returnFocusElement: null,
      triggerHandler: null,

      init() {
        this.afterSwapHandler = (event) => {
          if (event.target?.id === "command-palette-results") {
            this.$nextTick(() => this.syncResults());
          }
        };
        this.triggerHandler = (event) => {
          const trigger = event.target?.closest?.("[data-command-palette-trigger]");
          if (!trigger) {
            return;
          }

          event.preventDefault();
          this.openPalette({ detail: { source: trigger } });
        };

        document.body?.addEventListener("htmx:afterSwap", this.afterSwapHandler);
        document.addEventListener("click", this.triggerHandler);
        this.syncShortcutLabels();
        this.$nextTick(() => this.syncResults());
      },

      destroy() {
        document.body?.removeEventListener("htmx:afterSwap", this.afterSwapHandler);
        document.removeEventListener("click", this.triggerHandler);
      },

      get resultElements() {
        return Array.from(this.$root.querySelectorAll("[data-command-palette-result]"));
      },

      syncShortcutLabels() {
        const shortcutPlatform = navigator.userAgentData?.platform || navigator.userAgent || "";
        const isApplePlatform = /Mac|iPhone|iPad|iPod/i.test(shortcutPlatform);
        const label = isApplePlatform ? "Cmd K" : "Ctrl K";
        document
          .querySelectorAll("[data-command-palette-shortcut]")
          .forEach((element) => {
            element.textContent = label;
          });
      },

      handleGlobalKeydown(event) {
        const key = String(event.key || "").toLowerCase();
        const isPaletteShortcut =
          key === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;

        if (isPaletteShortcut) {
          event.preventDefault();
          if (this.open) {
            this.$refs.input?.focus();
            this.$refs.input?.select();
          } else {
            this.openPalette({ detail: { source: document.activeElement } });
          }
          return;
        }

        if (!this.open || event.key !== "Escape") {
          return;
        }

        event.preventDefault();
        this.closePalette();
      },

      openPalette(event) {
        if (!this.open) {
          this.returnFocusElement = event?.detail?.source || document.activeElement;
          this.previousBodyOverflow = document.body.style.overflow;
          document.body.style.overflow = "hidden";
        }

        this.open = true;
        this.$nextTick(() => {
          this.$refs.input?.focus();
          this.$refs.input?.select();
          this.syncResults();
        });
      },

      closePalette() {
        if (!this.open) {
          return;
        }

        this.open = false;
        document.body.style.overflow = this.previousBodyOverflow;
        this.activeIndex = -1;
        this.activeResultId = "";

        if (
          this.returnFocusElement &&
          document.contains(this.returnFocusElement) &&
          typeof this.returnFocusElement.focus === "function"
        ) {
          this.returnFocusElement.focus();
        }
        this.returnFocusElement = null;
      },

      syncResults() {
        const results = this.resultElements;
        this.activeIndex = results.length > 0 ? 0 : -1;
        this.applyActiveResult();
      },

      moveSelection(delta) {
        const results = this.resultElements;
        if (results.length === 0) {
          this.activeIndex = -1;
          this.activeResultId = "";
          return;
        }

        const currentIndex = this.activeIndex < 0 ? 0 : this.activeIndex;
        this.activeIndex = (currentIndex + delta + results.length) % results.length;
        this.applyActiveResult();
        results[this.activeIndex]?.scrollIntoView({ block: "nearest" });
      },

      applyActiveResult() {
        const results = this.resultElements;
        let activeElement = null;
        results.forEach((element, index) => {
          const selected = index === this.activeIndex;
          element.setAttribute("aria-selected", selected.toString());
          element.classList.toggle("is-active", selected);
          if (selected) {
            activeElement = element;
          }
        });
        this.activeResultId = activeElement?.id || "";
      },

      openActiveResult() {
        const results = this.resultElements;
        const result = results[this.activeIndex] || results[0];
        if (!result?.href) {
          return;
        }

        window.location.assign(result.href);
      },

      trapFocus(event) {
        if (!this.open) {
          return;
        }

        const elements = focusableElements(this.$refs.panel);
        if (elements.length === 0) {
          event.preventDefault();
          return;
        }

        const firstElement = elements[0];
        const lastElement = elements[elements.length - 1];
        if (!this.$refs.panel.contains(document.activeElement)) {
          event.preventDefault();
          firstElement.focus();
        } else if (event.shiftKey && document.activeElement === firstElement) {
          event.preventDefault();
          lastElement.focus();
        } else if (!event.shiftKey && document.activeElement === lastElement) {
          event.preventDefault();
          firstElement.focus();
        }
      },
    }));

    Alpine.data("deleteAccountDialog", () => ({
      confirmation: "",
      open: false,
      previousBodyOverflow: "",
      returnFocusElement: null,
      submitLabel: "Yes, delete my account",

      get confirmed() {
        return this.confirmation === "DELETE";
      },

      init() {
        this.submitLabel = this.$refs.submit?.textContent || this.submitLabel;
      },

      show(event) {
        this.returnFocusElement = event?.currentTarget || document.activeElement;
        this.previousBodyOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        this.confirmation = "";
        this.open = true;
        this.$nextTick(() => this.$refs.confirmation?.focus());
      },

      close() {
        this.open = false;
        this.confirmation = "";
        document.body.style.overflow = this.previousBodyOverflow;

        if (
          this.returnFocusElement &&
          document.contains(this.returnFocusElement) &&
          typeof this.returnFocusElement.focus === "function"
        ) {
          this.returnFocusElement.focus();
        }
      },

      submit(event) {
        if (!this.confirmed) {
          event.preventDefault();
          this.$refs.confirmation?.focus();
          return;
        }

        if (this.$refs.submit) {
          this.$refs.submit.disabled = true;
          this.$refs.submit.setAttribute("aria-disabled", "true");
          this.$refs.submit.textContent = "Deleting...";
        }
      },

      trapFocus(event) {
        if (!this.open || event.key !== "Tab") {
          return;
        }

        const elements = focusableElements(this.$refs.panel);
        if (elements.length === 0) {
          event.preventDefault();
          return;
        }

        const firstElement = elements[0];
        const lastElement = elements[elements.length - 1];
        if (!this.$refs.panel.contains(document.activeElement)) {
          event.preventDefault();
          firstElement.focus();
        } else if (event.shiftKey && document.activeElement === firstElement) {
          event.preventDefault();
          lastElement.focus();
        } else if (!event.shiftKey && document.activeElement === lastElement) {
          event.preventDefault();
          firstElement.focus();
        }
      },
    }));

    Alpine.data("feedbackWidget", () => ({
      feedback: "",
      open: false,
      submitting: false,
      submitLabel: "Send feedback",

      init() {
        this.submitLabel = this.$refs.submit?.textContent || this.submitLabel;
      },

      toggleFeedback() {
        if (this.open) {
          this.closeFeedback();
        } else {
          this.openFeedback();
        }
      },

      openFeedback() {
        this.open = true;
        this.$nextTick(() => this.$refs.feedbackInput?.focus());
      },

      closeFeedback() {
        this.open = false;
      },

      async submitFeedback(event) {
        event.preventDefault();
        if (this.submitting) {
          return;
        }

        const feedback = this.feedback.trim();
        if (!feedback) {
          Rowset.showMessage?.("Enter feedback before sending.", "warning", {
            autoDismiss: false,
          });
          this.$refs.feedbackInput?.focus();
          return;
        }

        this.submitting = true;
        try {
          const response = await fetch("/api/submit-feedback", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": csrfToken(),
            },
            body: JSON.stringify({ feedback, page: window.location.pathname }),
          });
          const data = await parseJsonResponse(response);

          if (!response.ok || data.success === false) {
            throw new Error(data.message || "Failed to submit feedback. Please try again.");
          }

          this.feedback = "";
          this.closeFeedback();
          Rowset.showMessage?.(data.message || "Feedback submitted successfully.", "success");
        } catch (error) {
          Rowset.showMessage?.(error.message || "Failed to submit feedback. Please try again.", "error", {
            autoDismiss: false,
          });
        } finally {
          this.submitting = false;
        }
      },
    }));

    Alpine.data("datasetProject", () => ({
      init() {
        this.$nextTick(() => this.syncSections());
      },

      syncSections() {
        const projectKey = this.$refs.projectSelect?.value || "";
        let selectedOptionIsValid = false;

        for (const option of this.$refs.sectionSelect?.options || []) {
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
          this.$refs.sectionSelect.value = "";
        }
      },
    }));

    Alpine.data("rowBulkActions", () => ({
      action: "",
      version: 0,

      init() {
        this.$nextTick(() => this.sync());
      },

      get checkboxes() {
        return Array.from(this.$root.querySelectorAll("[data-row-checkbox]"));
      },

      get selectedCheckboxes() {
        this.version;
        return this.checkboxes.filter((checkbox) => checkbox.checked);
      },

      get selectedCount() {
        return this.selectedCheckboxes.length;
      },

      toggleAll(event) {
        this.checkboxes.forEach((checkbox) => {
          checkbox.checked = event.currentTarget.checked;
        });
        this.sync();
      },

      sync() {
        this.version += 1;
        const selectAll = this.$refs.selectAll;
        if (!selectAll) {
          return;
        }

        selectAll.checked = this.checkboxes.length > 0 && this.selectedCount === this.checkboxes.length;
        selectAll.indeterminate = this.selectedCount > 0 && this.selectedCount < this.checkboxes.length;
      },

      confirm(event) {
        if (this.action !== "delete") {
          return;
        }

        if (this.selectedCount === 0) {
          event.preventDefault();
          return;
        }

        const rowLabel = this.selectedCount === 1 ? "row" : "rows";
        if (!window.confirm(`Delete ${this.selectedCount} selected ${rowLabel}? This cannot be undone.`)) {
          event.preventDefault();
        }
      },
    }));

    Alpine.data("rowInlineEdit", () => ({
      openFields: [],

      edit(fieldId) {
        if (!this.openFields.includes(fieldId)) {
          this.openFields.push(fieldId);
        }

        this.$nextTick(() => {
          const input = this.$root.querySelector(`[data-row-edit-input="${fieldId}"]`);
          if (!input) {
            return;
          }

          input.disabled = false;
          if (input.value === "") {
            input.value = input.dataset.originalValue || "";
          }
          input.focus();
          input.setSelectionRange(input.value.length, input.value.length);
        });
      },

      cancel() {
        for (const input of this.$root.querySelectorAll("[data-row-edit-input]")) {
          input.value = input.dataset.originalValue || "";
          input.disabled = true;
        }
        this.openFields = [];
      },

      hasOpenInput() {
        return this.openFields.length > 0;
      },

      isEditing(fieldId) {
        return this.openFields.includes(fieldId);
      },
    }));

    Alpine.data("rowColumnMenu", () => ({
      repositionFrame: null,
      triggerElement: null,

      init() {
        this.returnFocus = this.returnFocus.bind(this);
        this.scheduleRepositionDialog = this.scheduleRepositionDialog.bind(this);
        this.repositionDialog = this.repositionDialog.bind(this);
        this.$refs.dialog?.addEventListener("close", this.returnFocus);
      },

      destroy() {
        this.$refs.dialog?.removeEventListener("close", this.returnFocus);
        this.removePositionListeners();
      },

      open(event) {
        event.preventDefault();
        this.triggerElement = event.currentTarget;

        if (!this.$refs.dialog.open) {
          if (typeof this.$refs.dialog.showModal === "function") {
            this.$refs.dialog.showModal();
          } else {
            this.$refs.dialog.setAttribute("open", "");
          }
          this.addPositionListeners();
        }

        this.$nextTick(() => {
          positionDialog(this.$refs.dialog, this.triggerElement);
          this.$refs.dialog
            ?.querySelector("select, input:not([type='hidden']), button[type='submit']")
            ?.focus();
        });
      },

      close(event) {
        event?.preventDefault();
        if (typeof this.$refs.dialog.close === "function") {
          this.$refs.dialog.close();
        } else {
          this.$refs.dialog.removeAttribute("open");
          this.returnFocus();
        }
      },

      returnFocus() {
        this.removePositionListeners();
        this.triggerElement?.focus();
        this.triggerElement = null;
      },

      repositionDialog() {
        this.repositionFrame = null;
        if (this.$refs.dialog?.open) {
          positionDialog(this.$refs.dialog, this.triggerElement);
        }
      },

      scheduleRepositionDialog() {
        if (this.repositionFrame !== null) {
          return;
        }

        this.repositionFrame = window.requestAnimationFrame(this.repositionDialog);
      },

      addPositionListeners() {
        window.addEventListener("resize", this.scheduleRepositionDialog);
        window.addEventListener("scroll", this.scheduleRepositionDialog, true);
      },

      removePositionListeners() {
        window.removeEventListener("resize", this.scheduleRepositionDialog);
        window.removeEventListener("scroll", this.scheduleRepositionDialog, true);
        if (this.repositionFrame !== null) {
          window.cancelAnimationFrame(this.repositionFrame);
          this.repositionFrame = null;
        }
      },
    }));

    Alpine.data("docsToc", () => ({
      headingIds: [],
      handleScroll: null,
      observer: null,
      scrollFrame: null,
      visibleSectionIds: null,

      init() {
        this.generateTableOfContents();
        if (this.setupIntersectionObserver()) {
          return;
        }

        this.highlightCurrentSection();
        this.handleScroll = () => this.scheduleScrollHighlight();
        window.addEventListener("scroll", this.handleScroll, { passive: true });
      },

      destroy() {
        if (this.observer) {
          this.observer.disconnect();
          this.observer = null;
        }
        if (this.handleScroll) {
          window.removeEventListener("scroll", this.handleScroll);
        }
        if (this.scrollFrame !== null) {
          window.cancelAnimationFrame(this.scrollFrame);
          this.scrollFrame = null;
        }
      },

      generateTableOfContents() {
        const headings = Array.from(this.$refs.content?.querySelectorAll("h2") || []);
        if (headings.length === 0) {
          if (this.$refs.sidebar) {
            this.$refs.sidebar.style.display = "none";
          }
          return;
        }

        this.$refs.list.innerHTML = "";
        this.headingIds = [];
        headings.forEach((heading) => {
          const headingText = heading.textContent.trim();
          if (!heading.id) {
            heading.id = this.generateSlug(headingText);
          }
          this.headingIds.push(heading.id);

          const listItem = document.createElement("li");
          const link = document.createElement("a");
          link.href = `#${heading.id}`;
          link.textContent = headingText;
          link.dataset.section = heading.id;
          link.className =
            "block rounded-lg px-3 py-1.5 text-sm text-gray-600 transition-colors hover:bg-slate-100 hover:text-gray-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100";
          link.addEventListener("click", (event) => {
            event.preventDefault();
            this.scrollToSection(heading.id);
          });

          listItem.appendChild(link);
          this.$refs.list.appendChild(listItem);
        });
      },

      setupIntersectionObserver() {
        const headings = Array.from(this.$refs.content?.querySelectorAll("h2") || []);
        if (headings.length === 0 || typeof window.IntersectionObserver !== "function") {
          return false;
        }

        this.visibleSectionIds = new Set();
        this.observer = new window.IntersectionObserver(
          (entries) => {
            for (const entry of entries) {
              if (entry.isIntersecting) {
                this.visibleSectionIds.add(entry.target.id);
              } else {
                this.visibleSectionIds.delete(entry.target.id);
              }
            }

            const activeSectionId = this.headingIds.find((id) => this.visibleSectionIds.has(id));
            if (activeSectionId) {
              this.updateActiveLink(activeSectionId);
            }
          },
          {
            rootMargin: "-96px 0px -70% 0px",
            threshold: 0,
          },
        );

        headings.forEach((heading) => this.observer.observe(heading));
        return true;
      },

      generateSlug(text) {
        return text
          .toLowerCase()
          .replace(/[^\w\s-]/g, "")
          .replace(/\s+/g, "-")
          .replace(/-+/g, "-")
          .trim();
      },

      scrollToSection(sectionId) {
        const section = document.getElementById(sectionId);
        if (!section) {
          return;
        }

        const yOffset = -80;
        const offsetPosition = section.getBoundingClientRect().top + window.pageYOffset + yOffset;
        window.scrollTo({ behavior: "smooth", top: offsetPosition });
        this.updateActiveLink(sectionId);
      },

      scheduleScrollHighlight() {
        if (this.scrollFrame !== null) {
          return;
        }

        this.scrollFrame = window.requestAnimationFrame(() => {
          this.scrollFrame = null;
          this.highlightCurrentSection();
        });
      },

      highlightCurrentSection() {
        const headings = this.$refs.content?.querySelectorAll("h2") || [];
        const scrollPosition = window.scrollY + 100;
        let currentSectionId = "";

        headings.forEach((heading) => {
          if (scrollPosition >= heading.offsetTop) {
            currentSectionId = heading.id;
          }
        });

        if (currentSectionId) {
          this.updateActiveLink(currentSectionId);
        }
      },

      updateActiveLink(activeSectionId) {
        for (const link of this.$root.querySelectorAll("[data-section]")) {
          const isActive = link.dataset.section === activeSectionId;
          link.classList.toggle("bg-emerald-50", isActive);
          link.classList.toggle("text-emerald-700", isActive);
          link.classList.toggle("font-medium", isActive);
          link.classList.toggle("dark:bg-emerald-950/40", isActive);
          link.classList.toggle("dark:text-emerald-300", isActive);
          link.classList.toggle("text-gray-600", !isActive);
          link.classList.toggle("dark:text-slate-400", !isActive);
        }
      },
    }));
  });
})();
