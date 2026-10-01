// FileSh browser app. Runs on both the PC and other devices.

import { getJson } from "./api.js";
import { $, setIcon, setupConfirmDialog, storage } from "./dom.js";
import { checkForChanges, loadFiles, setupFiles } from "./files.js";
import { loadHistory, setupHistory } from "./history.js";
import { connectLive, disconnectLive, on } from "./live.js";
import { loadConnect, loadPendingRequests, setupConnect, startSharing } from "./connect.js";
import { setupPin, showPinScreen } from "./pin.js";
import { loadSettings, setupSettings } from "./settings.js";
import { hooks, state } from "./state.js";
import { loadTexts, setupTexts } from "./texts.js";
import { setDropText, setupUploads } from "./uploads.js";

const STATUS_INTERVAL = 10_000;
const FILES_INTERVAL = 3_000;
const PC_TABS = ["history", "settings"];

let started = false;

// ---------- Screens ----------

const MESSAGES = {
  stopped: {
    icon: "lock",
    title: "Sharing is stopped",
    text: "Sharing was stopped on the PC. Scan the new QR code when it is started again.",
  },
  stoppedPC: {
    icon: "lock",
    title: "Sharing is stopped",
    text: "Other devices can't connect. Your files stay on this PC.",
    button: "Start sharing",
    action: startSharing,
  },
  offline: {
    icon: "wifi-off",
    title: "Can't reach your PC",
    text: "Check that FileSh is running and both devices are on the same network.",
    button: "Retry",
    action: refreshStatus,
  },
};

let messageAction = null;

function showMessage(kind) {
  const message = MESSAGES[kind];
  $("app").hidden = true;
  $("status").hidden = true;
  $("pin-screen").hidden = true;
  $("message").hidden = false;
  setIcon($("message-icon"), message.icon);
  $("message-title").textContent = message.title;
  $("message-text").textContent = message.text;
  $("message-btn").hidden = !message.button;
  $("message-btn").textContent = message.button || "";
  messageAction = message.action || null;
}

function showApp() {
  $("message").hidden = true;
  $("pin-screen").hidden = true;
  $("app").hidden = false;
  $("status").hidden = false;
}

// ---------- Status ----------

async function refreshStatus() {
  let status;
  try {
    status = await getJson("/api/status");
  } catch (error) {
    if (error.status === 401) {
      disconnectLive();
      return showPinScreen();
    }
    if (error.status === 503) {
      disconnectLive();
      return showMessage("stopped");
    }
    if (!$("app").hidden) {
      $("status").classList.add("offline");
      $("status-text").textContent = "Offline";
      return;
    }
    return showMessage("offline");
  }

  state.isPC = status.is_pc;
  $("public-warning").hidden = !status.public_network;

  if (state.isPC && !status.sharing) {
    state.sharing = false;
    return showMessage("stoppedPC");
  }
  const sharingRestarted = !state.sharing;
  state.sharing = true;
  const firstTime = $("app").hidden;
  showApp();

  $("status").classList.remove("offline");
  $("status").classList.toggle("clickable", state.isPC);
  $("status-text").textContent = state.isPC
    ? `${status.devices} ${status.devices === 1 ? "device" : "devices"} online`
    : "Online";

  if (firstTime) {
    if (!started) setupLayout();
    started = true;
    connectLive();
    loadFiles(state.path);
    loadTexts();
    showTab(state.tab);
  }
  if (state.isPC && (firstTime || sharingRestarted)) {
    loadConnect();
    loadPendingRequests();
  }
}

function setupLayout() {
  $("connect-panel").hidden = !state.isPC;
  $("app").classList.toggle("with-connect", state.isPC);
  for (const tab of document.querySelectorAll("[data-pc-only]")) tab.hidden = !state.isPC;
  setDropText(state.isPC);
  const saved = storage.get("filesh-tab");
  if (saved && (state.isPC || !PC_TABS.includes(saved))) state.tab = saved;
}

// ---------- Tabs ----------

function showTab(name) {
  state.tab = name;
  storage.set("filesh-tab", name);
  for (const tab of document.querySelectorAll(".tab")) {
    const selected = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    $(`panel-${tab.dataset.tab}`).hidden = !selected;
  }
  if (name === "history") loadHistory();
  if (name === "settings") loadSettings();
}

function setupTabs() {
  const tabs = [...document.querySelectorAll(".tab")];
  for (const tab of tabs) {
    tab.addEventListener("click", () => showTab(tab.dataset.tab));
    tab.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      const visible = tabs.filter((t) => !t.hidden);
      const step = event.key === "ArrowRight" ? 1 : -1;
      const next = visible[(visible.indexOf(tab) + step + visible.length) % visible.length];
      next.focus();
      showTab(next.dataset.tab);
    });
  }
}

// ---------- Dark mode ----------

function effectiveTheme() {
  const chosen = document.documentElement.dataset.theme;
  if (chosen) return chosen;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  const dark = effectiveTheme() === "dark";
  setIcon($("theme-icon"), dark ? "sun" : "moon");
  $("theme-btn").setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
}

function setupTheme() {
  const saved = storage.get("filesh-theme");
  applyTheme(saved === "dark" || saved === "light" ? saved : null);
  $("theme-btn").addEventListener("click", () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    storage.set("filesh-theme", next);
    applyTheme(next);
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(null));
}

// ---------- Start ----------

function init() {
  // The token was saved in a cookie by the server; remove it from the address bar and history.
  if (location.search) history.replaceState(null, "", "/");

  hooks.refreshStatus = refreshStatus;
  hooks.reloadFiles = () => loadFiles(state.path, true);

  setupTheme();
  setupConfirmDialog();
  setupTabs();
  setupFiles();
  setupUploads();
  setupTexts();
  setupHistory();
  setupSettings();
  setupConnect();
  setupPin();
  $("message-btn").addEventListener("click", () => messageAction?.());

  // The live connection closes when access ends (stopped sharing, new token).
  on("close", (event) => {
    if (event.code === 4001 || event.code === 4003) refreshStatus();
  });

  refreshStatus();
  setInterval(refreshStatus, STATUS_INTERVAL);
  setInterval(checkForChanges, FILES_INTERVAL);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      refreshStatus();
      checkForChanges();
    }
  });
}

init();
