// Choosing files and folders, drag and drop, waiting for the PC to accept, and uploads
// that continue after the connection drops.

import { api, getJson, sendJson } from "./api.js";
import { $, button, el, fileIcon, formatDuration, formatSize, icon, plural, shortName, toast } from "./dom.js";
import { on } from "./live.js";
import { hooks, state } from "./state.js";

const PARALLEL_UPLOADS = 2;
const DONE_ITEM_DELAY = 5_000;
const MAX_RETRIES = 8;
const MAX_FILES = 10_000;
const DECISION_POLL = 3_000;
const DECISION_TIMEOUT = 130_000;

let selected = []; // [{ file, folders }]
const queue = [];
let active = 0;
let sentInBatch = 0;
const waiting = new Map(); // transfer ID -> callback with the PC's answer

// ---------- Choosing files ----------

function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

function describe(items) {
  const total = items.reduce((sum, item) => sum + item.file.size, 0);
  const roots = new Set(items.map((item) => item.folders.split("/")[0]));
  let label;
  if (items.length === 1) label = shortName(items[0].file.name);
  else if (roots.size === 1 && !roots.has("")) label = `${[...roots][0]} · ${plural(items.length, "file")}`;
  else label = plural(items.length, "file");
  return `${label} · ${formatSize(total)}`;
}

function setSelection(items) {
  selected = items;
  const selection = $("selection");
  selection.hidden = items.length === 0;
  selection.textContent = items.length ? describe(items) : "";
  $("send-btn").disabled = items.length === 0;
  $("clear-selection-btn").hidden = items.length === 0;
}

function fromFolderInput(files) {
  // webkitRelativePath is like "Trip/2026/beach.jpg"; keep the folders.
  return files.map((file) => {
    const parts = (file.webkitRelativePath || file.name).split("/");
    return { file, folders: parts.slice(0, -1).join("/") };
  });
}

// Must be called while the drop event is running: the browser clears the data afterwards.
async function filesFromDrop(dataTransfer) {
  const entries = [...dataTransfer.items]
    .filter((item) => item.kind === "file")
    .map((item) => item.webkitGetAsEntry?.())
    .filter(Boolean);
  if (entries.length === 0) return [...dataTransfer.files].map((file) => ({ file, folders: "" }));

  const result = [];
  async function walk(entry, folders) {
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      result.push({ file, folders });
    } else if (entry.isDirectory) {
      const path = folders ? `${folders}/${entry.name}` : entry.name;
      const reader = entry.createReader();
      let batch;
      do {
        batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        for (const child of batch) await walk(child, path);
      } while (batch.length > 0);
    }
  }
  for (const entry of entries) await walk(entry, "");
  return result;
}

function setupDragAndDrop() {
  let depth = 0;
  const hasFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");
  const canDrop = () => !$("app").hidden && state.tab === "files";
  const dropzone = $("dropzone");

  document.addEventListener("dragenter", (event) => {
    if (!hasFiles(event) || !canDrop()) return;
    depth += 1;
    dropzone.classList.add("dragging");
  });
  document.addEventListener("dragleave", (event) => {
    if (!hasFiles(event)) return;
    depth = Math.max(0, depth - 1);
    if (depth === 0) dropzone.classList.remove("dragging");
  });
  document.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return;
    // Always cancel, so a dropped file never replaces the page.
    event.preventDefault();
    event.dataTransfer.dropEffect = canDrop() ? "copy" : "none";
  });
  document.addEventListener("drop", async (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    depth = 0;
    dropzone.classList.remove("dragging");
    if (!canDrop()) return;
    try {
      sendItems(await filesFromDrop(event.dataTransfer));
    } catch {
      toast("Some dropped files could not be read", "error");
    }
  });
}

// ---------- Asking the PC ----------

async function sendItems(items) {
  if (items.length === 0) return;
  if (items.length > MAX_FILES) {
    toast(`Send at most ${MAX_FILES.toLocaleString()} files at a time`, "error");
    return;
  }
  const dir = state.path;
  let request;
  try {
    request = await sendJson("/api/transfers", "POST", {
      dir,
      files: items.map(({ file, folders }) => ({ name: file.name, folders, size: file.size })),
    });
  } catch (error) {
    if (error.status === 401 || error.status === 503) hooks.refreshStatus();
    toast(error.message, "error");
    return;
  }

  if (request.status !== "accepted") {
    const answer = await waitForDecision(request.id, items);
    if (answer === "rejected") toast("The PC declined the files", "warning");
    if (answer === "expired") toast("No answer from the PC. Open FileSh on the PC and try again.", "warning");
    if (answer !== "accepted") return;
  }
  for (const { file, folders } of items) queue.push(createUpload(file, folders, dir, request.id));
  pumpQueue();
}

function waitForDecision(id, items) {
  return new Promise((resolve) => {
    const row = createRow(describe(items), items.length === 1 ? fileIcon(items[0].file.name) : "folder");
    row.item.classList.add("waiting");
    row.info.textContent = "Waiting for the PC to accept…";

    let finished = false;
    const finish = (status) => {
      if (finished) return;
      finished = true;
      clearInterval(poll);
      clearTimeout(timeout);
      waiting.delete(id);
      removeRow(row);
      resolve(status);
    };
    setActions(row, [
      [
        "Cancel",
        () => {
          finish("cancelled");
          api(`/api/transfers/${id}`, { method: "DELETE" }).catch(() => {});
        },
      ],
    ]);
    waiting.set(id, finish);
    // The answer normally arrives as a live event; this check is a fallback.
    const poll = setInterval(async () => {
      try {
        const result = await getJson(`/api/transfers/${id}`);
        if (result.status !== "pending") finish(result.status);
      } catch (error) {
        if (error.status === 404) finish("expired");
      }
    }, DECISION_POLL);
    const timeout = setTimeout(() => finish("expired"), DECISION_TIMEOUT);
  });
}

// ---------- Progress rows ----------

function createRow(label, iconName) {
  const item = el("li", "upload");
  const head = el("div", "upload-head");
  const name = el("span", "upload-name", label);
  name.title = label;
  const percent = el("span", "upload-percent", "");
  head.append(icon(iconName), name, percent);

  const bar = el("div", "bar");
  const fill = el("div", "bar-fill");
  bar.append(fill);

  const foot = el("div", "upload-foot");
  const info = el("span", "upload-status", "");
  const actions = el("span", "upload-actions");
  foot.append(info, actions);

  item.append(head, bar, foot);
  $("uploads").append(item);
  $("uploads-section").hidden = false;
  return { item, percent, fill, info, actions };
}

function removeRow(row) {
  row.item.remove();
  $("uploads-section").hidden = $("uploads").children.length === 0;
}

function setActions(row, buttons) {
  row.actions.replaceChildren(
    ...buttons.map(([label, handler]) => button(label, "btn btn-secondary", handler)),
  );
}

function createUpload(file, folders, dir, transfer) {
  const label = folders ? `${folders}/${file.name}` : file.name;
  const row = createRow(shortName(label, 48), fileIcon(file.name));
  row.percent.textContent = "Waiting";
  row.info.textContent = formatSize(file.size);
  const upload = {
    ...row,
    file,
    folders,
    dir,
    transfer,
    id: null,
    offset: 0,
    xhr: null,
    retries: 0,
    jumps: 0,
    timer: null,
    cancelled: false,
  };
  setActions(upload, [["Cancel", () => cancelUpload(upload)]]);
  return upload;
}

// ---------- Uploading ----------

function pumpQueue() {
  while (active < PARALLEL_UPLOADS && queue.length > 0) startUpload(queue.shift());
  if (active === 0 && queue.length === 0 && sentInBatch > 0) {
    toast(`${plural(sentInBatch, "file")} sent`);
    sentInBatch = 0;
    hooks.reloadFiles();
  }
}

async function startUpload(upload) {
  active += 1;
  upload.item.classList.remove("failed", "done");
  setActions(upload, [["Cancel", () => cancelUpload(upload)]]);
  if (upload.retries) upload.info.textContent = "Reconnecting…";
  try {
    if (upload.id) {
      // Continue where the last attempt stopped.
      try {
        upload.offset = (await getJson(`/api/uploads/${upload.id}`)).offset;
      } catch (error) {
        if (error.status !== 404) throw error;
        upload.id = null;
      }
    }
    if (!upload.id) {
      const started = await sendJson("/api/uploads", "POST", {
        dir: upload.dir,
        folders: upload.folders,
        name: upload.file.name,
        size: upload.file.size,
        modified: upload.file.lastModified / 1000,
        transfer: upload.transfer,
      });
      upload.id = started.id;
      upload.offset = started.offset;
    }
  } catch (error) {
    active -= 1;
    handleError(upload, error.status, error.message);
    return;
  }
  if (upload.cancelled) {
    active -= 1;
    pumpQueue();
    return;
  }
  sendData(upload);
}

function sendData(upload) {
  const { file } = upload;
  const offset = upload.offset;
  const xhr = new XMLHttpRequest();
  upload.xhr = xhr;

  let lastLoaded = 0;
  let lastTime = performance.now();
  let speed = 0;

  xhr.upload.addEventListener("progress", (event) => {
    if (!event.lengthComputable) return;
    const now = performance.now();
    const elapsed = (now - lastTime) / 1000;
    if (elapsed >= 0.5) {
      const current = (event.loaded - lastLoaded) / elapsed;
      speed = speed ? speed * 0.7 + current * 0.3 : current;
      lastLoaded = event.loaded;
      lastTime = now;
    }
    const loaded = offset + event.loaded;
    const pct = file.size ? Math.floor((loaded / file.size) * 100) : 100;
    upload.percent.textContent = `${pct}%`;
    upload.fill.style.width = `${pct}%`;
    const parts = [`${formatSize(loaded)} of ${formatSize(file.size)}`];
    if (speed > 0) parts.push(`${formatSize(speed)}/s`, formatDuration((file.size - loaded) / speed));
    upload.info.textContent = parts.join(" · ");
  });

  xhr.addEventListener("load", () => {
    upload.xhr = null;
    let data = {};
    try {
      data = JSON.parse(xhr.responseText);
    } catch {
      // Not JSON.
    }
    if (xhr.status === 201) {
      active -= 1;
      finishUpload(upload);
      pumpQueue();
      return;
    }
    // The server has a different position (e.g. after a reconnect): continue from there.
    if ((xhr.status === 200 || xhr.status === 409) && typeof data.offset === "number" && upload.jumps < 5) {
      upload.jumps += 1;
      upload.offset = data.offset;
      sendData(upload);
      return;
    }
    active -= 1;
    handleError(upload, xhr.status, data.error || `Error ${xhr.status}`);
  });
  xhr.addEventListener("error", () => {
    upload.xhr = null;
    active -= 1;
    handleError(upload, 0, "Connection lost");
  });
  xhr.addEventListener("abort", () => {
    upload.xhr = null;
    active -= 1;
    pumpQueue();
  });

  xhr.open("PUT", `/api/uploads/${upload.id}?offset=${offset}`);
  xhr.setRequestHeader("Content-Type", "application/octet-stream");
  xhr.send(file.slice(offset));
}

function handleError(upload, status, message) {
  if (upload.cancelled) {
    pumpQueue();
    return;
  }
  if (status === 401 || status === 503) {
    failUpload(upload, message);
    hooks.refreshStatus();
    pumpQueue();
    return;
  }
  const temporary = status === 0 || status === 409 || status === 429 || (status >= 500 && status !== 507);
  if (temporary && upload.retries < MAX_RETRIES) {
    const delay = Math.min(30, 2 ** (upload.retries + 1));
    upload.retries += 1;
    upload.info.textContent = `${message}. Trying again in ${delay} s…`;
    upload.timer = setTimeout(() => {
      upload.timer = null;
      queue.unshift(upload);
      pumpQueue();
    }, delay * 1000);
    pumpQueue();
    return;
  }
  failUpload(upload, message);
  pumpQueue();
}

function finishUpload(upload) {
  upload.item.classList.add("done");
  upload.percent.textContent = "100%";
  upload.fill.style.width = "100%";
  upload.info.textContent = "Done";
  setActions(upload, []);
  sentInBatch += 1;
  setTimeout(() => removeRow(upload), DONE_ITEM_DELAY);
}

function failUpload(upload, message) {
  upload.item.classList.add("failed");
  upload.info.textContent = message;
  setActions(upload, [
    [
      "Retry",
      () => {
        upload.retries = 0;
        upload.jumps = 0;
        upload.percent.textContent = "Waiting";
        setActions(upload, [["Cancel", () => cancelUpload(upload)]]);
        queue.push(upload);
        pumpQueue();
      },
    ],
    ["Remove", () => cancelUpload(upload)],
  ]);
}

function cancelUpload(upload) {
  upload.cancelled = true;
  clearTimeout(upload.timer);
  const queued = queue.indexOf(upload);
  if (queued >= 0) queue.splice(queued, 1);
  upload.xhr?.abort();
  // Delete the unfinished file on the PC.
  if (upload.id) api(`/api/uploads/${upload.id}`, { method: "DELETE" }).catch(() => {});
  removeRow(upload);
}

// ---------- Start ----------

export function setupUploads() {
  const supportsFolders = "webkitdirectory" in document.createElement("input") && !isIOS();
  $("folder-btn").hidden = !supportsFolders;

  $("dropzone").addEventListener("click", () => $("file-input").click());
  $("folder-btn").addEventListener("click", () => $("folder-input").click());
  $("file-input").addEventListener("change", (event) => {
    setSelection([...event.target.files].map((file) => ({ file, folders: "" })));
    event.target.value = "";
  });
  $("folder-input").addEventListener("change", (event) => {
    setSelection(fromFolderInput([...event.target.files]));
    event.target.value = "";
  });
  $("clear-selection-btn").addEventListener("click", () => setSelection([]));
  $("send-btn").addEventListener("click", () => {
    const items = selected;
    setSelection([]);
    sendItems(items);
  });
  setupDragAndDrop();

  on("transfer-decided", (event) => waiting.get(event.id)?.(event.status));
}

export function setDropText(isPC) {
  $("dropzone-text").textContent = isPC ? "Drag files here or click to choose" : "Tap to choose files";
}
