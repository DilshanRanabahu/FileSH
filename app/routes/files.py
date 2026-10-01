"""Browse, download, preview, and upload files."""

import asyncio
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from app.context import AppContext, get_ctx
from app.media import (
    PREVIEW_TYPES,
    THUMBNAIL_TYPES,
    attachment,
    make_thumbnail,
    thumbnail_path,
    zip_folder,
)
from app.security import device_id, is_local, require_access
from app.transfers import PartialUpload
from app.utils import (
    PART_PREFIX,
    PART_SUFFIX,
    clean_filename,
    clean_folders,
    is_part_file,
    relative_path,
    safe_path,
    unique_path,
)

router = APIRouter(dependencies=[Depends(require_access)])


def _folder(ctx: AppContext, path: str) -> Path:
    directory = safe_path(ctx.root, path)
    if not directory.is_dir():
        raise HTTPException(404, "Folder not found")
    return directory


def _file(ctx: AppContext, path: str) -> Path:
    target = safe_path(ctx.root, path)
    if not target.is_file() or is_part_file(target.name):
        raise HTTPException(404, "File not found")
    return target


async def _record_sent(request: Request, name: str, path: str, size: int | None) -> None:
    """Downloads by other devices go into the history; the PC's own downloads don't."""
    if is_local(request):
        return
    ctx = get_ctx(request)
    await ctx.history.add("sent", name, path, size, ctx.device_label(device_id(request)))
    await ctx.hub.send({"type": "history"}, pcs_only=True)


# ---------- Browse and download ----------


def _list_directory(directory: Path) -> list[dict]:
    items = []
    with os.scandir(directory) as entries:
        for entry in entries:
            # Links are skipped so nothing outside the shared folder is listed.
            if entry.is_symlink() or entry.is_junction() or is_part_file(entry.name):
                continue
            try:
                is_dir = entry.is_dir()
                info = entry.stat()
            except OSError:
                continue
            items.append(
                {
                    "name": entry.name,
                    "type": "folder" if is_dir else "file",
                    "size": 0 if is_dir else info.st_size,
                    "modified": info.st_mtime,
                }
            )
    items.sort(key=lambda item: (item["type"] != "folder", item["name"].casefold()))
    return items


@router.get("/api/files")
async def files(request: Request, path: str = "") -> dict:
    ctx = get_ctx(request)
    directory = _folder(ctx, path)
    items = await asyncio.to_thread(_list_directory, directory)
    return {"path": relative_path(ctx.root, directory), "items": items}


@router.get("/api/download")
async def download(request: Request, path: str) -> FileResponse:
    ctx = get_ctx(request)
    target = _file(ctx, path)
    await _record_sent(request, target.name, relative_path(ctx.root, target), target.stat().st_size)
    return FileResponse(target, filename=target.name, media_type="application/octet-stream")


@router.get("/api/download-zip")
async def download_zip(request: Request, path: str = "") -> StreamingResponse:
    ctx = get_ctx(request)
    directory = _folder(ctx, path)
    name = directory.name if directory != ctx.root.resolve() else "Shared"
    await _record_sent(request, f"{name}.zip", relative_path(ctx.root, directory), None)
    return StreamingResponse(
        zip_folder(directory, name, ctx.settings.chunk_size),
        media_type="application/zip",
        headers={"Content-Disposition": attachment(f"{name}.zip")},
    )


@router.get("/api/preview")
async def preview(request: Request, path: str) -> FileResponse:
    """Show safe image, video, and audio types in the browser (SECURITY.md 2.6)."""
    target = _file(get_ctx(request), path)
    media_type = PREVIEW_TYPES.get(target.suffix.lower())
    if media_type is None:
        raise HTTPException(415, "This file can't be previewed")
    return FileResponse(
        target, media_type=media_type, filename=target.name, content_disposition_type="inline"
    )


@router.get("/api/thumbnail")
async def thumbnail(request: Request, path: str) -> FileResponse:
    ctx = get_ctx(request)
    source = _file(ctx, path)
    if source.suffix.lower() not in THUMBNAIL_TYPES:
        raise HTTPException(415, "No thumbnail for this file")
    target = thumbnail_path(ctx.thumbnail_dir, source)
    if not target.exists():
        async with ctx.thumbnail_slots:
            if not target.exists() and not await asyncio.to_thread(make_thumbnail, source, target):
                raise HTTPException(415, "No thumbnail for this file")
    return FileResponse(target, media_type="image/jpeg")


# ---------- Upload (resumable) ----------


class UploadStart(BaseModel):
    dir: str = ""
    folders: str = ""
    name: str
    size: int = Field(ge=0)
    modified: float | None = None
    transfer: str | None = None


def _check_space(ctx: AppContext, directory: Path, needed: int) -> None:
    if shutil.disk_usage(directory).free - needed < ctx.settings.min_free_space:
        raise HTTPException(507, "Not enough space on the PC")


@asynccontextmanager
async def _upload_slot(ctx: AppContext, device: str) -> AsyncIterator[None]:
    if ctx.uploads_per_device[device] >= ctx.settings.max_parallel_uploads:
        raise HTTPException(429, "Too many uploads at the same time")
    ctx.uploads_per_device[device] += 1
    try:
        yield
    finally:
        ctx.uploads_per_device[device] -= 1


@router.post("/api/uploads")
async def start_upload(request: Request, body: UploadStart) -> dict:
    """Start an upload, or continue an unfinished one of the same file."""
    ctx = get_ctx(request)
    directory = _folder(ctx, body.dir)
    rel_dir = relative_path(ctx.root, directory)
    folders = clean_folders(body.folders)
    name = clean_filename(body.name)
    if body.size > ctx.settings.max_file_size:
        limit_gb = ctx.settings.max_file_size / 1024**3
        raise HTTPException(413, f"This file is larger than the limit ({limit_gb:g} GB)")

    device = device_id(request)
    key = (rel_dir, folders, name, body.size, body.modified)
    existing = ctx.uploads.find(device, key)
    if existing is not None and existing.part.exists():
        return {"id": existing.id, "offset": existing.offset}

    transfer_file = None
    if not is_local(request) and ctx.settings.ask_before_receiving:
        # The PC must have accepted exactly this file for this device (SECURITY.md 2.15).
        transfer_file = ctx.transfers.find_file(
            body.transfer or "", device, rel_dir, folders, name, body.size
        )
        if transfer_file is None:
            raise HTTPException(403, "This file was not accepted on the PC")

    _check_space(ctx, directory, body.size)
    target_dir = safe_path(ctx.root, "/".join(p for p in (rel_dir, folders) if p))
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise HTTPException(409, "A file has the same name as the folder") from None
    part = target_dir / f"{PART_PREFIX}{uuid.uuid4().hex}{PART_SUFFIX}"
    part.touch()

    upload = PartialUpload(
        id=uuid.uuid4().hex,
        device_id=device,
        key=key,
        directory=target_dir,
        name=name,
        size=body.size,
        part=part,
        transfer_file=transfer_file,
    )
    try:
        ctx.uploads.add(upload)
    except ValueError:
        part.unlink(missing_ok=True)
        raise HTTPException(429, "Too many unfinished uploads") from None
    return {"id": upload.id, "offset": 0}


def _get_upload(request: Request, upload_id: str) -> PartialUpload:
    upload = get_ctx(request).uploads.get(upload_id, device_id(request))
    if upload is None:
        raise HTTPException(404, "Upload not found")
    return upload


@router.get("/api/uploads/{upload_id}")
async def upload_status(request: Request, upload_id: str) -> dict:
    upload = _get_upload(request, upload_id)
    return {"offset": upload.offset, "size": upload.size, "active": upload.active}


@router.put("/api/uploads/{upload_id}", response_model=None)
async def upload_data(request: Request, upload_id: str, offset: int) -> Response | dict:
    """Write bytes starting at `offset`. If the connection drops, the bytes already received
    are kept, and the browser continues from there."""
    ctx = get_ctx(request)
    upload = _get_upload(request, upload_id)
    try:
        length = int(request.headers["content-length"])
    except (KeyError, ValueError):
        raise HTTPException(411, "File size is missing") from None
    if upload.active:
        raise HTTPException(409, "This file is already being uploaded")
    if offset != upload.offset:
        return JSONResponse({"error": "Wrong position", "offset": upload.offset}, 409)
    if length < 0 or offset + length > upload.size:
        raise HTTPException(400, "File is larger than announced")
    _check_space(ctx, upload.directory, upload.size - offset)

    device = device_id(request)
    disconnected = False
    async with (
        _upload_slot(ctx, device),
        upload.lock,
        aiofiles.open(upload.part, "r+b") as file,
    ):
        await file.seek(offset)
        await file.truncate()
        buffer = bytearray()
        received = 0
        try:
            async for chunk in request.stream():
                received += len(chunk)
                if received > length:
                    raise HTTPException(400, "File is larger than announced")
                buffer += chunk
                if len(buffer) >= ctx.settings.chunk_size:
                    await file.write(buffer)
                    upload.offset += len(buffer)
                    upload.updated = time.monotonic()
                    buffer.clear()
        except ClientDisconnect:
            disconnected = True
        finally:
            # Keep what arrived, so the upload can continue from here.
            if buffer:
                await file.write(buffer)
                upload.offset += len(buffer)
            upload.updated = time.monotonic()

    if disconnected:
        return Response(status_code=400)
    if upload.offset < upload.size:
        return {"offset": upload.offset, "done": False}
    return await _finish_upload(request, ctx, upload)


async def _finish_upload(request: Request, ctx: AppContext, upload: PartialUpload) -> Response:
    async with ctx.rename_lock:
        final = unique_path(upload.directory, upload.name)
        upload.part.rename(final)
    ctx.uploads.remove(upload, delete_file=False)
    if upload.transfer_file is not None:
        upload.transfer_file.done = True

    path = relative_path(ctx.root, final)
    device = ctx.device_label(device_id(request))
    await ctx.history.add("received", final.name, path, upload.size, device)
    await ctx.hub.files_changed({relative_path(ctx.root, final.parent)})
    await ctx.hub.send({"type": "history"}, pcs_only=True)
    return JSONResponse({"name": final.name, "path": path, "size": upload.size, "done": True}, 201)


@router.delete("/api/uploads/{upload_id}")
async def cancel_upload(request: Request, upload_id: str) -> dict:
    ctx = get_ctx(request)
    upload = _get_upload(request, upload_id)
    try:
        # Wait for a request that is still writing to notice the cancel.
        async with asyncio.timeout(10), upload.lock:
            ctx.uploads.remove(upload)
    except TimeoutError:
        raise HTTPException(409, "Upload is still running") from None
    return {"cancelled": True}
