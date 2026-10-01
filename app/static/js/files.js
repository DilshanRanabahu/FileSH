// The shared-files list, folder ZIP downloads, and the preview viewer.

import { getJson } from "./api.js";
import { $, el, extension, fileIcon, formatDate, formatSize, icon, joinPath, shortName, toast } from "./dom.js";
import { isLive, on } from "./live.js";
import { hooks, state } from "./state.js";

// Must match PREVIEW_TYPES and THUMBNAIL_TYPES in app/media.py.
const PREVIEW = {
  image: ["jpg", "jpeg", "png", "gif", "webp"],
  video: ["mp4", "m4v", "mov", "webm"],
  audio: ["mp3", "m4a", "aac", "wav", "ogg", "opus", "flac"],
};
const THUMBNAILS = ["jpg", "jpeg", "png", "gif", "webp", "bmp"];

let filesKey = "";
let filesRequest = 0;
let filesLoading = false;
let previewItems = [];
let previewIndex = 0;

const url = (endpoint, path) => `${endpoint}?path=${encodeURIComponent(path)}`;

function previewKind(name) {
  const ext = extension(name);
  return Object.keys(PREVIEW).find((kind) => PREVIEW[kind].includes(ext)) || null;
}

// `quiet` is used by automatic updates: no error toasts, and no redraw if nothing changed.
export async function loadFiles(path, quiet = false) {
  const request = ++filesRequest;
  filesLoading = true;
  let data;
  try {
    data = await getJson(url("/api/files", path));
  } catch (error) {
    if (request !== filesRequest) return;
    if (error.status === 401 || error.status === 503) return hooks.refreshStatus();
    if (error.status === 404 && path) return loadFiles("");
    if (!quiet) toast(error.message, "error");
    return;
  } finally {
    if (request === filesRequest) filesLoading = false;
  }
  // A newer request (for example, the user opened another folder) wins.
  if (request !== filesRequest) return;

  const key = JSON.stringify(data);
  if (quiet && key === filesKey) return;
  filesKey = key;
  state.path = data.path;
  renderBreadcrumb(data.path);
  renderFiles(data.items);
}

// Fallback when the live connection is down: check the open folder every few seconds.
export function checkForChanges() {
  if (isLive() || document.hidden || $("app").hidden || filesLoading) return;
  loadFiles(state.path, true);
}

function renderBreadcrumb(path) {
  const nav = $("breadcrumb");
  nav.replaceChildren();
  const parts = path ? path.split("/") : [];
  const crumbs = [{ name: "Shared", path: "" }];
  parts.forEach((part, i) => crumbs.push({ name: part, path: parts.slice(0, i + 1).join("/") }));

  crumbs.forEach((crumb, i) => {
    if (i > 0) nav.append(el("span", "crumb-sep", "›"));
    if (i === crumbs.length - 1) {
      const current = el("span", "crumb-current", crumb.name);
      current.setAttribute("aria-current", "page");
      nav.append(current);
    } else {
      const crumbButton = el("button", "crumb", crumb.name);
      crumbButton.type = "button";
      crumbButton.addEventListener("click", () => loadFiles(crumb.path));
      nav.append(crumbButton);
    }
  });
  $("zip-btn").href = url("/api/download-zip", path);
}

function thumbnailOrIcon(item, path) {
  if (!THUMBNAILS.includes(extension(item.name))) return icon(fileIcon(item.name));
  const img = el("img", "thumb");
  img.alt = "";
  img.loading = "lazy";
  img.decoding = "async";
  img.src = `${url("/api/thumbnail", path)}&v=${item.modified}`;
  img.addEventListener("error", () => img.replaceWith(icon(fileIcon(item.name))), { once: true });
  return img;
}

function renderFiles(items) {
  const list = $("file-list");
  list.replaceChildren();
  $("empty").hidden = items.length > 0;
  $("zip-btn").hidden = items.length === 0;
  previewItems = [];

  for (const item of items) {
    const row = el("li", "file-row");
    const path = joinPath(state.path, item.name);
    const isFolder = item.type === "folder";
    const kind = isFolder ? null : previewKind(item.name);

    let main;
    if (isFolder) {
      main = el("button", "row-main");
      main.type = "button";
      main.addEventListener("click", () => loadFiles(path));
    } else if (kind) {
      const index = previewItems.push({ name: item.name, path, kind }) - 1;
      main = el("button", "row-main");
      main.type = "button";
      main.setAttribute("aria-label", `Preview ${item.name}`);
      main.addEventListener("click", () => openPreview(index));
    } else {
      main = el("a", "row-main");
      main.href = url("/api/download", path);
      main.download = item.name;
      main.setAttribute("aria-label", `Download ${item.name}`);
    }

    const text = el("span", "row-text");
    const name = el("span", "row-name", shortName(item.name));
    name.title = item.name;
    const meta = isFolder
      ? `Folder · ${formatDate(item.modified)}`
      : `${formatSize(item.size)} · ${formatDate(item.modified)}`;
    text.append(name, el("span", "row-meta", meta));
    main.append(isFolder ? icon("folder") : thumbnailOrIcon(item, path), text);
    if (isFolder) main.append(icon("chevron-right", "icon chevron"));

    const action = el("a", "icon-btn row-action");
    action.href = isFolder ? url("/api/download-zip", path) : url("/api/download", path);
    action.download = isFolder ? `${item.name}.zip` : item.name;
    const label = isFolder ? `Download ${item.name} as ZIP` : `Download ${item.name}`;
    action.setAttribute("aria-label", label);
    action.title = label;
    action.append(icon(isFolder ? "folder-down" : "download"));

    row.append(main, action);
    list.append(row);
  }
}

// ---------- Preview ----------

function openPreview(index) {
  previewIndex = index;
  showPreview();
  const dialog = $("preview-dialog");
  if (!dialog.open) dialog.showModal();
}

function showPreview() {
  const item = previewItems[previewIndex];
  const body = $("preview-body");
  body.replaceChildren();
  const src = url("/api/preview", item.path);
  let media;
  if (item.kind === "image") {
    media = el("img");
    media.alt = item.name;
  } else {
    media = el(item.kind);
    media.controls = true;
    media.preload = "metadata";
    if (item.kind === "video") media.playsInline = true;
  }
  media.src = src;
  media.addEventListener(
    "error",
    () => body.replaceChildren(el("p", "muted", "This file can't be shown here. Download it instead.")),
    { once: true },
  );
  body.append(media);

  $("preview-name").textContent = item.name;
  $("preview-name").title = item.name;
  $("preview-download").href = url("/api/download", item.path);
  $("preview-download").download = item.name;
  const many = previewItems.length > 1;
  $("preview-prev").hidden = !many;
  $("preview-next").hidden = !many;
  $("preview-count").textContent = many ? `${previewIndex + 1} of ${previewItems.length}` : "";
}

function movePreview(step) {
  if (previewItems.length < 2) return;
  previewIndex = (previewIndex + step + previewItems.length) % previewItems.length;
  showPreview();
}

export function setupFiles() {
  $("refresh-btn").addEventListener("click", () => loadFiles(state.path));
  $("preview-close").addEventListener("click", () => $("preview-dialog").close());
  $("preview-prev").addEventListener("click", () => movePreview(-1));
  $("preview-next").addEventListener("click", () => movePreview(1));
  $("preview-dialog").addEventListener("close", () => $("preview-body").replaceChildren());
  $("preview-dialog").addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") movePreview(-1);
    if (event.key === "ArrowRight") movePreview(1);
  });

  on("files", (event) => {
    if (!event.paths || event.paths.includes(state.path)) loadFiles(state.path, true);
  });
  // After reconnecting, events may have been missed.
  on("open", () => {
    if (!$("app").hidden) loadFiles(state.path, true);
  });
}
