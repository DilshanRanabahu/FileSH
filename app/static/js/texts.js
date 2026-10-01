// Sharing text and links between devices.

import { api, getJson, sendJson } from "./api.js";
import { $, button, confirmDialog, copyText, el, formatDate, toast } from "./dom.js";
import { on } from "./live.js";
import { hooks } from "./state.js";

const MAX_BYTES = 100 * 1024;

// A text that is just one web link becomes a clickable link; nothing else is ever a link.
function asLink(text) {
  const trimmed = text.trim();
  if (/\s/.test(trimmed)) return null;
  try {
    const url = new URL(trimmed);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

export async function loadTexts() {
  let items;
  try {
    items = await getJson("/api/texts");
  } catch (error) {
    if (error.status === 401 || error.status === 503) hooks.refreshStatus();
    return;
  }
  const list = $("text-list");
  list.replaceChildren();
  $("text-empty").hidden = items.length > 0;
  $("text-clear-btn").hidden = items.length === 0;

  for (const item of items) {
    const row = el("li", "text-item");
    const body = el("div", "text-body");
    const link = asLink(item.text);
    if (link) {
      const anchor = el("a", "", item.text.trim());
      anchor.href = link;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      body.append(anchor);
    } else {
      body.textContent = item.text;
    }

    const foot = el("div", "text-foot");
    const meta = el("span", "small muted", `${item.device} · ${formatDate(item.time)}`);
    const actions = el("span", "upload-actions");
    actions.append(
      button("Copy", "btn btn-secondary btn-small", async () => {
        const copied = await copyText(item.text);
        toast(copied ? "Copied" : "Could not copy. Select the text instead.", copied ? "success" : "error");
      }),
      button("Delete", "btn btn-danger btn-small", async () => {
        try {
          await api(`/api/texts/${encodeURIComponent(item.id)}`, { method: "DELETE" });
        } catch (error) {
          toast(error.message, "error");
        }
        loadTexts();
      }),
    );
    foot.append(meta, actions);
    row.append(body, foot);
    list.append(row);
  }
}

async function sendText() {
  const input = $("text-input");
  const text = input.value;
  if (!text.trim()) {
    input.focus();
    return;
  }
  if (new TextEncoder().encode(text).length > MAX_BYTES) {
    toast("Text is too long (limit 100 KB)", "error");
    return;
  }
  try {
    await sendJson("/api/texts", "POST", { text });
  } catch (error) {
    toast(error.message, "error");
    return;
  }
  input.value = "";
  toast("Text sent");
  loadTexts();
}

export function setupTexts() {
  $("text-send-btn").addEventListener("click", sendText);
  $("text-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) sendText();
  });
  $("text-clear-btn").addEventListener("click", async () => {
    const ok = await confirmDialog({
      title: "Clear all text?",
      text: "The text will be removed from all devices.",
      confirm: "Clear",
    });
    if (!ok) return;
    try {
      await api("/api/texts", { method: "DELETE" });
    } catch (error) {
      toast(error.message, "error");
    }
    loadTexts();
  });
  on("texts", loadTexts);
  on("open", loadTexts);
}
