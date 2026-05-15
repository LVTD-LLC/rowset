export async function copyTextToClipboard(text, { sourceElement } = {}) {
  if (!text) {
    return false;
  }

  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      // Fall back for browsers/contexts where clipboard permissions are blocked.
    }
  }

  if (sourceElement && typeof sourceElement.select === "function") {
    sourceElement.focus();
    sourceElement.select();
    try {
      return document.execCommand("copy");
    } catch (error) {
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
  } catch (error) {
    return false;
  } finally {
    textarea.remove();
  }
}
