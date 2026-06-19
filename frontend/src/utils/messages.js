const DEFAULT_TIMEOUT_MS = 8000;

const MESSAGE_TYPES = {
  error: {
    autoDismiss: false,
    buttonClasses: ["text-red-700", "hover:bg-red-100", "dark:text-red-200", "dark:hover:bg-red-900/60"],
    iconClasses: ["text-red-600", "dark:text-red-300"],
    path: "M10 18a8 8 0 100-16 8 8 0 000 16Zm-1-5a1 1 0 112 0 1 1 0 01-2 0Zm.25-7.25a.75.75 0 011.5 0v4.5a.75.75 0 01-1.5 0v-4.5Z",
    role: "alert",
    text: "Notification",
    toneClasses: ["border-red-200", "bg-red-50", "text-red-900", "dark:border-red-900/60", "dark:bg-red-950", "dark:text-red-100"],
  },
  info: {
    autoDismiss: true,
    buttonClasses: ["text-sky-700", "hover:bg-sky-100", "dark:text-sky-200", "dark:hover:bg-sky-900/60"],
    iconClasses: ["text-sky-600", "dark:text-sky-300"],
    path: "M10 18a8 8 0 100-16 8 8 0 000 16Zm0-11.25a.75.75 0 110-1.5.75.75 0 010 1.5Zm-.75 2.5a.75.75 0 011.5 0v4a.75.75 0 01-1.5 0v-4Z",
    role: "status",
    text: "Notification",
    toneClasses: ["border-sky-200", "bg-sky-50", "text-sky-950", "dark:border-sky-900/60", "dark:bg-sky-950", "dark:text-sky-100"],
  },
  success: {
    autoDismiss: true,
    buttonClasses: ["text-emerald-700", "hover:bg-emerald-100", "dark:text-emerald-200", "dark:hover:bg-emerald-900/60"],
    iconClasses: ["text-emerald-600", "dark:text-emerald-300"],
    path: "M10 18a8 8 0 100-16 8 8 0 000 16Zm3.857-9.809a.75.75 0 00-1.214-.882l-3.236 4.45-1.55-1.55a.75.75 0 10-1.06 1.061l2.17 2.17a.75.75 0 001.137-.089l3.753-5.16Z",
    role: "status",
    text: "Notification",
    toneClasses: ["border-emerald-200", "bg-emerald-50", "text-emerald-950", "dark:border-emerald-900/60", "dark:bg-emerald-950", "dark:text-emerald-100"],
  },
  warning: {
    autoDismiss: false,
    buttonClasses: ["text-amber-800", "hover:bg-amber-100", "dark:text-amber-100", "dark:hover:bg-amber-900/60"],
    iconClasses: ["text-amber-600", "dark:text-amber-300"],
    path: "M8.257 3.099c.765-1.36 2.72-1.36 3.486 0l6.518 11.59c.75 1.333-.213 2.986-1.743 2.986H3.482c-1.53 0-2.493-1.653-1.743-2.986l6.518-11.59ZM10 7a.75.75 0 00-.75.75v3.5a.75.75 0 001.5 0v-3.5A.75.75 0 0010 7Zm0 7a1 1 0 100-2 1 1 0 000 2Z",
    role: "status",
    text: "Notification",
    toneClasses: ["border-amber-200", "bg-amber-50", "text-amber-950", "dark:border-amber-900/60", "dark:bg-amber-950", "dark:text-amber-100"],
  },
};

export function showMessage(message, type = "error", options = {}) {
  const normalizedType = String(type || "").toLowerCase();
  const safeOptions = options || {};
  const safeType = MESSAGE_TYPES[normalizedType] ? normalizedType : "info";
  const config = MESSAGE_TYPES[safeType];
  const container = document.querySelector("[data-messages-container]") || createMessagesContainer();
  const item = createMessageElement(String(message || config.text), config, safeOptions);

  container.appendChild(item);
  return item;
}

function createMessagesContainer() {
  const container = document.createElement("div");
  container.dataset.controller = "messages";
  container.dataset.messagesContainer = "true";
  container.className = [
    "pointer-events-none",
    "fixed",
    "inset-x-4",
    "top-4",
    "z-50",
    "max-h-[calc(100vh-2rem)]",
    "space-y-3",
    "overflow-y-auto",
    "sm:left-auto",
    "sm:right-4",
    "sm:w-full",
    "sm:max-w-sm",
  ].join(" ");
  container.setAttribute("aria-label", "Notifications");
  document.body.appendChild(container);
  return container;
}

function createMessageElement(message, config, options) {
  const item = document.createElement("div");
  item.dataset.messagesTarget = "item";
  item.dataset.messagesAutoDismiss = String(options.autoDismiss ?? config.autoDismiss);
  item.dataset.messagesTimeout = String(options.timeout || DEFAULT_TIMEOUT_MS);
  item.setAttribute("role", config.role);
  item.setAttribute("aria-live", config.role === "alert" ? "assertive" : "polite");
  item.setAttribute("aria-atomic", "true");
  item.className = [
    "pointer-events-auto",
    "rounded-lg",
    "border",
    "p-4",
    "transition",
    "duration-200",
    "ease-out",
    "motion-reduce:transition-none",
    ...config.toneClasses,
  ].join(" ");

  const row = document.createElement("div");
  row.className = "flex items-start gap-3";

  const icon = createIcon(config);
  const text = document.createElement("p");
  text.className = "min-w-0 flex-1 break-words text-sm leading-6";
  text.textContent = message;

  const button = createDismissButton(config);

  row.append(icon, text, button);
  item.appendChild(row);
  return item;
}

function createIcon(config) {
  const wrapper = document.createElement("div");
  wrapper.className = "mt-0.5 flex-shrink-0";
  wrapper.setAttribute("aria-hidden", "true");

  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("class", ["h-5", "w-5", ...config.iconClasses].join(" "));
  icon.setAttribute("viewBox", "0 0 20 20");
  icon.setAttribute("fill", "currentColor");

  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("fill-rule", "evenodd");
  path.setAttribute("clip-rule", "evenodd");
  path.setAttribute("d", config.path);

  icon.appendChild(path);
  wrapper.appendChild(icon);
  return wrapper;
}

function createDismissButton(config) {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.action = "click->messages#dismiss";
  button.className = [
    "fb-focus",
    "inline-flex",
    "h-7",
    "w-7",
    "flex-shrink-0",
    "items-center",
    "justify-center",
    "rounded-full",
    ...config.buttonClasses,
  ].join(" ");
  button.setAttribute("aria-label", "Dismiss notification");

  const hiddenLabel = document.createElement("span");
  hiddenLabel.className = "sr-only";
  hiddenLabel.textContent = "Dismiss notification";

  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("class", "h-4 w-4");
  icon.setAttribute("fill", "none");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("stroke", "currentColor");
  icon.setAttribute("aria-hidden", "true");

  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  path.setAttribute("stroke-width", "2");
  path.setAttribute("d", "M6 18L18 6M6 6l12 12");

  icon.appendChild(path);
  button.append(hiddenLabel, icon);
  return button;
}
