// Transfer history (PC only).

import { api, getJson } from "./api.js";
import { $, confirmDialog, el, formatDate, formatSize, icon, shortName, toast } from "./dom.js";
import { on } from "./live.js";
import { state } from "./state.js";

export async function loadHistory() {
  if (!state.isPC) return;
  let entries;
  try {
    entries = await getJson("/api/history");
  } catch (error) {
    toast(error.message, "error");
    return;
  }
  const list = $("history-list");
  list.replaceChildren();
  $("history-empty").hidden = entries.length > 0;
  $("history-clear-btn").hidden = entries.length === 0;

  for (const entry of entries) {
    const received = entry.direction === "received";
    const row = el("li", "history-item");
    const direction = icon(received ? "arrow-down" : "arrow-up", `icon ${received ? "received" : "sent"}`);
    const text = el("span", "row-text");
    const name = el("span", "row-name", shortName(entry.name, 48));
    name.title = entry.path || entry.name;
    const parts = [received ? `Received from ${entry.device}` : `Sent to ${entry.device}`];
    if (typeof entry.size === "number") parts.push(formatSize(entry.size));
    parts.push(formatDate(entry.time));
    text.append(name, el("span", "row-meta", parts.join(" · ")));
    row.append(direction, text);
    list.append(row);
  }
}

export function setupHistory() {
  $("history-clear-btn").addEventListener("click", async () => {
    const ok = await confirmDialog({
      title: "Clear history?",
      text: "The list is cleared. Your files are not deleted.",
      confirm: "Clear",
    });
    if (!ok) return;
    try {
      await api("/api/history", { method: "DELETE" });
    } catch (error) {
      toast(error.message, "error");
    }
    loadHistory();
  });
  on("history", () => {
    if (state.tab === "history") loadHistory();
  });
}
