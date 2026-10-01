// PC only: QR code, PIN, connected devices, stop/start sharing, and incoming file requests.

import { api, getJson, sendJson } from "./api.js";
import { $, confirmDialog, el, formatSize, icon, plural, shortName, toast } from "./dom.js";
import { on } from "./live.js";
import { hooks, state } from "./state.js";

const requests = []; // incoming transfer requests waiting for an answer
let showing = null;

export async function loadConnect() {
  try {
    const info = await getJson("/api/connect");
    if (info.url) {
      $("qr").src = `/api/qr.svg?v=${Date.now()}`;
      $("qr").hidden = false;
      $("address").textContent = `${info.https ? "https://" : ""}${info.address}`;
    } else {
      $("qr").hidden = true;
      $("address").textContent = "No network found. Connect to Wi-Fi or Ethernet.";
    }
    $("pin").textContent = `${info.pin.slice(0, 3)} ${info.pin.slice(3)}`;
    $("discovery-line").hidden = !info.discovery_url;
    $("discovery-url").textContent = info.discovery_url || "";
  } catch (error) {
    toast(error.message, "error");
  }
}

// ---------- Devices ----------

function formatConnected(seconds) {
  if (seconds < 60) return "Connected just now";
  if (seconds < 3600) return `Connected ${Math.floor(seconds / 60)} min ago`;
  return `Connected ${Math.floor(seconds / 3600)} h ago`;
}

async function loadDevices() {
  let devices = [];
  try {
    devices = await getJson("/api/devices");
  } catch (error) {
    toast(error.message, "error");
  }
  const list = $("devices-list");
  list.replaceChildren();
  $("devices-empty").hidden = devices.length > 0;
  for (const device of devices) {
    const row = el("li", "device-item");
    const text = el("span", "row-text");
    text.append(
      el("span", "row-name", device.name),
      el("span", "row-meta", `${device.ip} · ${formatConnected(device.connected_seconds)}`),
    );
    row.append(icon("smartphone"), text);
    list.append(row);
  }
}

// ---------- Sharing ----------

async function stopSharing() {
  const ok = await confirmDialog({
    title: "Stop sharing?",
    text: "All connected devices will be disconnected. You will get a new QR code and PIN next time.",
    confirm: "Stop",
  });
  if (!ok) return;
  try {
    await api("/api/stop", { method: "POST" });
    toast("Sharing stopped");
  } catch (error) {
    toast(error.message, "error");
  }
  hooks.refreshStatus();
}

export async function startSharing() {
  try {
    await api("/api/start", { method: "POST" });
    toast("Sharing started");
  } catch (error) {
    toast(error.message, "error");
  }
  hooks.refreshStatus();
}

// ---------- Incoming files ----------

function updateTitle() {
  document.title = requests.length ? `(${requests.length}) FileSh` : "FileSh";
}

function showNextRequest() {
  updateTitle();
  const dialog = $("transfer-dialog");
  if (showing || requests.length === 0) return;
  showing = requests[0];
  $("transfer-from").textContent = `${showing.device} wants to send:`;
  const list = $("transfer-files");
  list.replaceChildren(
    ...showing.files.map((file) => {
      const item = el("li", "", `${shortName(file.name, 44)} (${formatSize(file.size)})`);
      item.title = file.name;
      return item;
    }),
  );
  const more = showing.count - showing.files.length;
  const total = `Total: ${plural(showing.count, "file")}, ${formatSize(showing.size)}`;
  $("transfer-total").textContent = more > 0 ? `and ${more} more. ${total}` : total;
  dialog.showModal();
}

function closeRequest(id) {
  const index = requests.findIndex((request) => request.id === id);
  if (index >= 0) requests.splice(index, 1);
  if (showing && showing.id === id) {
    showing = null;
    $("transfer-dialog").close();
  }
  showNextRequest();
}

async function decide(accept) {
  if (!showing) return;
  const { id } = showing;
  try {
    await sendJson(`/api/transfers/${id}/decision`, "POST", { accept });
    if (accept) toast("Files accepted");
  } catch (error) {
    toast(error.message, "error");
  }
  closeRequest(id);
}

function addRequest(request) {
  if (!requests.some((item) => item.id === request.id)) requests.push(request);
  showNextRequest();
}

export async function loadPendingRequests() {
  try {
    for (const request of await getJson("/api/transfers")) addRequest(request);
  } catch {
    // Not important; new requests also arrive as live events.
  }
}

export function setupConnect() {
  $("stop-btn").addEventListener("click", stopSharing);
  $("status").addEventListener("click", () => {
    if (!state.isPC) return;
    loadDevices();
    $("devices-dialog").showModal();
  });
  $("transfer-accept").addEventListener("click", () => decide(true));
  $("transfer-reject").addEventListener("click", () => decide(false));
  // Esc must not dismiss a request without an answer.
  $("transfer-dialog").addEventListener("cancel", (event) => event.preventDefault());

  on("transfer", (event) => addRequest(event.transfer));
  on("transfer-closed", (event) => closeRequest(event.id));
  on("devices", () => {
    hooks.refreshStatus();
    if ($("devices-dialog").open) loadDevices();
  });
  on("sharing", (event) => {
    if (event.reason) toast(event.reason, "warning");
    hooks.refreshStatus();
  });
  on("open", () => {
    if (state.isPC) loadPendingRequests();
  });
}
