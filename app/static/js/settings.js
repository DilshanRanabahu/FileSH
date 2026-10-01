// Settings page (PC only).

import { api, getJson, sendJson } from "./api.js";
import { $, el, toast } from "./dom.js";
import { disconnectLive } from "./live.js";
import { state } from "./state.js";

let current = null;

function render(settings) {
  current = settings;
  $("shared-dir-input").value = settings.shared_dir;
  $("ask-input").checked = settings.ask_before_receiving;
  $("discoverable-input").checked = settings.discoverable;
  $("https-input").checked = settings.https;
  $("startup-input").checked = settings.start_with_windows;
  $("windows-card").hidden = !settings.start_with_windows_supported;
  $("restart-banner").hidden = !settings.restart_required;

  const select = $("auto-stop-input");
  select.replaceChildren(
    ...settings.auto_stop_choices.map((minutes) => {
      const option = el("option", "", minutes ? `After ${minutes} minutes` : "Never");
      option.value = String(minutes);
      return option;
    }),
  );
  select.value = String(settings.auto_stop_minutes);

  const fingerprint = $("fingerprint-line");
  fingerprint.hidden = !(settings.https_running && settings.certificate_fingerprint);
  fingerprint.textContent = settings.certificate_fingerprint
    ? `Certificate fingerprint (SHA-256): ${settings.certificate_fingerprint}`
    : "";
  $("version").textContent = `FileSh ${settings.version}`;
}

export async function loadSettings() {
  if (!state.isPC) return;
  try {
    render(await getJson("/api/settings"));
  } catch (error) {
    toast(error.message, "error");
  }
}

async function save(changes, message = "Saved") {
  try {
    render(await sendJson("/api/settings", "POST", changes));
    toast(message);
    return true;
  } catch (error) {
    toast(error.message, "error");
    if (current) render(current); // undo the switch in the page
    return false;
  }
}

async function restart() {
  $("restart-btn").disabled = true;
  try {
    await api("/api/restart", { method: "POST" });
  } catch (error) {
    toast(error.message, "error");
    $("restart-btn").disabled = false;
    return;
  }
  disconnectLive();
  $("app").hidden = true;
  $("message").hidden = false;
  $("message-title").textContent = "Restarting FileSh…";
  $("message-text").textContent = "This takes a few seconds.";
  $("message-btn").hidden = true;
  // Wait until the server answers again, then load the page fresh.
  const started = Date.now();
  await new Promise((resolve) => setTimeout(resolve, 1500));
  while (Date.now() - started < 30_000) {
    try {
      await getJson("/api/status");
      location.reload();
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  location.reload();
}

export function setupSettings() {
  $("browse-btn").addEventListener("click", async () => {
    let result;
    try {
      result = await sendJson("/api/choose-folder", "POST");
    } catch (error) {
      toast(error.message, "error");
      return;
    }
    if (result.path) {
      $("shared-dir-input").value = result.path;
      save({ shared_dir: result.path }, "Shared folder changed");
    }
  });
  $("save-dir-btn").addEventListener("click", () => {
    save({ shared_dir: $("shared-dir-input").value }, "Shared folder changed");
  });
  $("open-folder-btn").addEventListener("click", () => {
    api("/api/open-folder", { method: "POST" }).catch((error) => toast(error.message, "error"));
  });
  $("ask-input").addEventListener("change", (event) => save({ ask_before_receiving: event.target.checked }));
  $("discoverable-input").addEventListener("change", (event) => save({ discoverable: event.target.checked }));
  $("https-input").addEventListener("change", (event) => save({ https: event.target.checked }));
  $("startup-input").addEventListener("change", (event) => save({ start_with_windows: event.target.checked }));
  $("auto-stop-input").addEventListener("change", (event) => {
    save({ auto_stop_minutes: Number(event.target.value) });
  });
  $("restart-btn").addEventListener("click", restart);
}
