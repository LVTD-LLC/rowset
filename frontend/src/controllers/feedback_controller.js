import { Controller } from "@hotwired/stimulus";
import { showMessage } from "../utils/messages";

export default class extends Controller {
  static targets = ["toggleButton", "overlay", "formContainer", "feedbackInput", "submit"];

  connect() {
    this.isOpen = false;
    this.isSubmitting = false;
    this.submitLabel = this.hasSubmitTarget ? this.submitTarget.textContent : "Send feedback";
    this.openTimer = null;
    this.focusTimer = null;
    this.closeTimer = null;

    this.handleKeydownBound = this.handleKeydown.bind(this);
    document.addEventListener("keydown", this.handleKeydownBound);
  }

  disconnect() {
    document.removeEventListener("keydown", this.handleKeydownBound);
    this.clearTimers();
  }

  toggleFeedback() {
    if (this.isOpen) {
      this.closeFeedback();
    } else {
      this.openFeedback();
    }
  }

  openFeedback() {
    this.clearTimers();
    this.overlayTarget.classList.remove("opacity-0", "pointer-events-none");
    this.overlayTarget.classList.add("opacity-100", "pointer-events-auto");

    this.openTimer = window.setTimeout(() => {
      this.formContainerTarget.classList.remove("scale-95");
      this.formContainerTarget.classList.add("scale-100");
    }, 10);

    this.focusTimer = window.setTimeout(() => {
      this.feedbackInputTarget.focus();
    }, 300);

    this.isOpen = true;
  }

  closeFeedback() {
    this.clearTimers();
    this.formContainerTarget.classList.remove("scale-100");
    this.formContainerTarget.classList.add("scale-95");

    this.closeTimer = window.setTimeout(() => {
      this.overlayTarget.classList.remove("opacity-100", "pointer-events-auto");
      this.overlayTarget.classList.add("opacity-0", "pointer-events-none");
    }, 100);

    this.isOpen = false;
  }

  closeIfClickedOutside(event) {
    if (event.target === this.overlayTarget) {
      this.closeFeedback();
    }
  }

  handleKeydown(event) {
    // Close with Escape key
    if (event.key === "Escape" && this.isOpen) {
      event.preventDefault();
      this.closeFeedback();
    }

    if (event.key === "Enter" && !event.shiftKey && this.isOpen &&
        document.activeElement === this.feedbackInputTarget) {
      event.preventDefault();
      this.submitFeedback(event);
    }
  }

  async submitFeedback(event) {
    event.preventDefault();
    if (this.isSubmitting) return;

    const feedback = this.feedbackInputTarget.value.trim();

    if (!feedback) {
      showMessage("Enter feedback before sending.", "warning", { autoDismiss: false });
      this.feedbackInputTarget.focus();
      return;
    }

    this.setSubmitting(true);

    try {
      const csrfToken = this.csrfToken();
      if (!csrfToken) {
        throw new Error("Unable to submit feedback. Refresh the page and try again.");
      }

      const response = await fetch("/api/submit-feedback", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ feedback, page: window.location.pathname }),
      });
      const data = await this.parseResponse(response);

      if (!response.ok) {
        throw new Error(this.errorMessageForStatus(response.status, data.message));
      }

      if (data.success === false || data.status === false) {
        throw new Error(data.message || "Failed to submit feedback. Please try again.");
      }

      this.resetForm();
      this.closeFeedback();
      showMessage(data.message || "Feedback submitted successfully.", "success");
    } catch (error) {
      showMessage(error.message || "Failed to submit feedback. Please try again.", "error", {
        autoDismiss: false,
      });
    } finally {
      this.setSubmitting(false);
    }
  }

  resetForm() {
    this.feedbackInputTarget.value = "";
  }

  setSubmitting(isSubmitting) {
    this.isSubmitting = isSubmitting;

    if (!this.hasSubmitTarget) return;

    this.submitTarget.disabled = isSubmitting;
    this.submitTarget.setAttribute("aria-disabled", String(isSubmitting));
    this.submitTarget.textContent = isSubmitting ? "Sending..." : this.submitLabel;
  }

  async parseResponse(response) {
    try {
      return await response.json();
    } catch (_error) {
      return {};
    }
  }

  errorMessageForStatus(status, message) {
    if (message) return message;

    if (status === 401 || status === 403) {
      return "You need to sign in again before sending feedback.";
    }

    if (status === 429) {
      return "Too many feedback attempts. Wait a moment and try again.";
    }

    return "Failed to submit feedback. Please try again.";
  }

  csrfToken() {
    const input = document.querySelector("[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  clearTimers() {
    [this.openTimer, this.focusTimer, this.closeTimer].forEach((timer) => {
      if (timer) {
        window.clearTimeout(timer);
      }
    });
    this.openTimer = null;
    this.focusTimer = null;
    this.closeTimer = null;
  }
}
