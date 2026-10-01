// Small helpers shared by all modules.
// Text from files and devices is always set with textContent, never as HTML (SECURITY.md 2.6).

export const ICONS = "/static/icons.svg";

export const $ = (id) => document.getElementById(id);

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function icon(name, className = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `${ICONS}#${name}`);
  svg.append(use);
  return svg;
}

export function setIcon(useElement, name) {
  useElement.setAttribute("href", `${ICONS}#${name}`);
}

export function button(label, className, onClick) {
  const node = el("button", className, label);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

export function toast(message, type = "success") {
  const icons = { success: "check-circle", warning: "alert-triangle", error: "x-circle" };
  const item = el("div", `toast ${type}`);
  item.append(icon(icons[type]), el("span", "", message));
  $("toasts").append(item);
  setTimeout(() => {
    item.classList.add("leaving");
    setTimeout(() => item.remove(), 200);
  }, 3000);
}

export function plural(count, word) {
  return `${count} ${count === 1 ? word : `${word}s`}`;
}

export function formatSize(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unit]}`;
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return `${Math.ceil(seconds)} s left`;
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} min left`;
  return `${Math.floor(seconds / 3600)} h ${Math.ceil((seconds % 3600) / 60)} min left`;
}

export function formatDate(timestamp) {
  const date = new Date(timestamp * 1000);
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return `Today, ${time}`;
  if (date.toDateString() === yesterday.toDateString()) return `Yesterday, ${time}`;
  const sameYear = date.getFullYear() === today.getFullYear();
  return date.toLocaleDateString([], {
    day: "numeric",
    month: "short",
    year: sameYear ? undefined : "numeric",
  });
}

// Cut long names in the middle so the extension stays visible.
export function shortName(name, max = 40) {
  if (name.length <= max) return name;
  const end = Math.min(12, Math.floor(max / 3));
  return `${name.slice(0, max - end - 1)}…${name.slice(-end)}`;
}

export function extension(name) {
  return name.includes(".") ? name.split(".").pop().toLowerCase() : "";
}

const FILE_TYPES = {
  image: ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "svg", "tif", "tiff"],
  video: ["mp4", "mov", "mkv", "avi", "webm", "3gp", "m4v", "wmv"],
  audio: ["mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "wma"],
  archive: ["zip", "rar", "7z", "tar", "gz", "bz2", "xz"],
  document: ["pdf", "doc", "docx", "txt", "rtf", "odt", "xls", "xlsx", "csv", "ppt", "pptx", "md"],
};

export function fileIcon(name) {
  const ext = extension(name);
  for (const [type, extensions] of Object.entries(FILE_TYPES)) {
    if (extensions.includes(ext)) return type;
  }
  return "file";
}

export function joinPath(base, name) {
  return base ? `${base}/${name}` : name;
}

// Browser storage only for small per-device conveniences; it can be unavailable.
export const storage = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Not important if it can't be saved.
    }
  },
};

export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall back below.
    }
  }
  // Plain HTTP pages can't use the clipboard API; use a hidden text box instead.
  const area = el("textarea", "visually-hidden");
  area.value = text;
  area.setAttribute("readonly", "");
  document.body.append(area);
  area.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  area.remove();
  return copied;
}

let confirmResolve = null;

// A styled replacement for window.confirm().
export function confirmDialog({ title, text, confirm }) {
  const dialog = $("confirm-dialog");
  $("confirm-title").textContent = title;
  $("confirm-text").textContent = text;
  $("confirm-ok").textContent = confirm;
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => {
    confirmResolve = resolve;
  });
}

export function setupConfirmDialog() {
  $("confirm-dialog").addEventListener("close", () => {
    confirmResolve?.($("confirm-dialog").returnValue === "ok");
    confirmResolve = null;
  });
}
