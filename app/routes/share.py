"""Transfer approvals, text sharing, and transfer history."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.context import get_ctx
from app.security import device_id, device_name, is_local, require_access, require_local
from app.transfers import TransferFile
from app.utils import clean_filename, clean_folders, relative_path, safe_path

router = APIRouter()

MAX_FILES_PER_TRANSFER = 10_000


# ---------- Accept or reject incoming files ----------


class TransferFileBody(BaseModel):
    name: str
    folders: str = ""
    size: int = Field(ge=0)


class TransferBody(BaseModel):
    dir: str = ""
    files: list[TransferFileBody] = Field(min_length=1, max_length=MAX_FILES_PER_TRANSFER)


class DecisionBody(BaseModel):
    accept: bool


@router.post("/api/transfers", dependencies=[Depends(require_access)])
async def request_transfer(request: Request, body: TransferBody) -> dict:
    """Ask the PC to accept files. The PC itself, or "ask before receiving" off: accepted."""
    ctx = get_ctx(request)
    if is_local(request) or not ctx.settings.ask_before_receiving:
        return {"id": None, "status": "accepted"}

    directory = safe_path(ctx.root, body.dir)
    if not directory.is_dir():
        raise HTTPException(404, "Folder not found")
    files = [
        TransferFile(clean_folders(f.folders), clean_filename(f.name), f.size) for f in body.files
    ]
    name = device_name(request.headers.get("user-agent", ""))
    try:
        transfer = ctx.transfers.create(
            device_id(request), name, relative_path(ctx.root, directory), files
        )
    except ValueError as exc:
        raise HTTPException(429, str(exc)) from None

    await ctx.hub.send({"type": "transfer", "transfer": transfer.summary()}, pcs_only=True)
    count = len(files)
    ctx.notify(f"{name} wants to send {count} {'file' if count == 1 else 'files'}. Open FileSh.")
    return {"id": transfer.id, "status": transfer.status}


@router.get("/api/transfers", dependencies=[Depends(require_local)])
async def pending_transfers(request: Request) -> list[dict]:
    return [t.summary() for t in get_ctx(request).transfers.pending()]


@router.get("/api/transfers/{transfer_id}", dependencies=[Depends(require_access)])
async def transfer_status(request: Request, transfer_id: str) -> dict:
    ctx = get_ctx(request)
    owner = None if is_local(request) else device_id(request)
    transfer = ctx.transfers.get(transfer_id, owner)
    if transfer is None:
        raise HTTPException(404, "Request not found")
    return {"id": transfer.id, "status": transfer.status}


@router.delete("/api/transfers/{transfer_id}", dependencies=[Depends(require_access)])
async def cancel_transfer(request: Request, transfer_id: str) -> dict:
    ctx = get_ctx(request)
    transfer = ctx.transfers.get(transfer_id, device_id(request))
    if transfer is None:
        raise HTTPException(404, "Request not found")
    if transfer.status == "pending":
        transfer.status = "cancelled"
        await ctx.hub.send({"type": "transfer-closed", "id": transfer.id}, pcs_only=True)
    return {"id": transfer.id, "status": transfer.status}


@router.post(
    "/api/transfers/{transfer_id}/decision",
    dependencies=[Depends(require_local)],
)
async def decide_transfer(request: Request, transfer_id: str, body: DecisionBody) -> dict:
    ctx = get_ctx(request)
    transfer = ctx.transfers.get(transfer_id)
    if transfer is None:
        raise HTTPException(404, "Request not found")
    if transfer.status != "pending":
        raise HTTPException(409, f"This request is already {transfer.status}")
    transfer.status = "accepted" if body.accept else "rejected"
    event = {"type": "transfer-decided", "id": transfer.id, "status": transfer.status}
    await ctx.hub.send(event, device_id=transfer.device_id)
    await ctx.hub.send({"type": "transfer-closed", "id": transfer.id}, pcs_only=True)
    return {"id": transfer.id, "status": transfer.status}


# ---------- Text and clipboard sharing ----------


class TextBody(BaseModel):
    text: str


@router.get("/api/texts", dependencies=[Depends(require_access)])
async def texts(request: Request) -> list[dict]:
    return get_ctx(request).texts.list()


@router.post("/api/texts", dependencies=[Depends(require_access)])
async def add_text(request: Request, body: TextBody) -> dict:
    ctx = get_ctx(request)
    if not body.text.strip():
        raise HTTPException(400, "Type something first")
    if len(body.text.encode()) > ctx.settings.max_text_length:
        raise HTTPException(413, "Text is too long (limit 100 KB)")
    item = ctx.texts.add(body.text, ctx.device_label(device_id(request)))
    await ctx.hub.send({"type": "texts"})
    return item


@router.delete("/api/texts/{item_id}", dependencies=[Depends(require_access)])
async def delete_text(request: Request, item_id: str) -> dict:
    ctx = get_ctx(request)
    if not ctx.texts.remove(item_id):
        raise HTTPException(404, "Text not found")
    await ctx.hub.send({"type": "texts"})
    return {"deleted": True}


@router.delete("/api/texts", dependencies=[Depends(require_access)])
async def clear_texts(request: Request) -> dict:
    ctx = get_ctx(request)
    ctx.texts.clear()
    await ctx.hub.send({"type": "texts"})
    return {"deleted": True}


# ---------- History (PC only) ----------


@router.get("/api/history", dependencies=[Depends(require_local)])
async def history(request: Request) -> list[dict]:
    return get_ctx(request).history.list()


@router.delete("/api/history", dependencies=[Depends(require_local)])
async def clear_history(request: Request) -> dict:
    ctx = get_ctx(request)
    await ctx.history.clear()
    await ctx.hub.send({"type": "history"}, pcs_only=True)
    return {"deleted": True}
