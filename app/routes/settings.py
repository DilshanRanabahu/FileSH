"""Settings page (PC only)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import desktop
from app.config import AUTO_STOP_CHOICES, VERSION
from app.context import AppContext, get_ctx
from app.security import require_local

router = APIRouter(dependencies=[Depends(require_local)])


class SettingsBody(BaseModel):
    shared_dir: str | None = None
    ask_before_receiving: bool | None = None
    auto_stop_minutes: int | None = None
    https: bool | None = None
    discoverable: bool | None = None
    start_with_windows: bool | None = None


def _settings(ctx: AppContext) -> dict:
    settings = ctx.settings
    return {
        "shared_dir": str(settings.shared_dir),
        "ask_before_receiving": settings.ask_before_receiving,
        "auto_stop_minutes": settings.auto_stop_minutes,
        "auto_stop_choices": list(AUTO_STOP_CHOICES),
        "https": settings.https,
        "https_running": ctx.running_https,
        "certificate_fingerprint": ctx.tls_fingerprint,
        "discoverable": settings.discoverable,
        "discovery_name": ctx.discovery.hostname,
        "start_with_windows": desktop.start_with_windows_enabled(),
        "start_with_windows_supported": desktop.start_with_windows_supported(),
        "restart_required": settings.https != ctx.running_https,
        "version": VERSION,
    }


@router.get("/api/settings")
async def get_settings(request: Request) -> dict:
    return _settings(get_ctx(request))


@router.post("/api/settings")
async def update_settings(request: Request, body: SettingsBody) -> dict:
    ctx = get_ctx(request)
    settings = ctx.settings

    if body.auto_stop_minutes is not None and body.auto_stop_minutes not in AUTO_STOP_CHOICES:
        raise HTTPException(400, "Choose one of the auto-stop options")
    if body.shared_dir is not None:
        try:
            folder = desktop.validate_shared_folder(body.shared_dir, settings.data_dir)
        except desktop.FolderError as exc:
            raise HTTPException(400, str(exc)) from None
        if folder != settings.shared_dir:
            await ctx.change_shared_folder(folder)
    if body.ask_before_receiving is not None:
        settings.ask_before_receiving = body.ask_before_receiving
    if body.auto_stop_minutes is not None:
        settings.auto_stop_minutes = body.auto_stop_minutes
    if body.https is not None:
        settings.https = body.https
    if body.discoverable is not None and body.discoverable != settings.discoverable:
        settings.discoverable = body.discoverable
        if body.discoverable:
            await ctx.start_discovery()
        else:
            await ctx.stop_discovery()
    if body.start_with_windows is not None and desktop.start_with_windows_supported():
        try:
            await asyncio.to_thread(desktop.set_start_with_windows, body.start_with_windows)
        except OSError:
            raise HTTPException(500, "Could not change the Windows start-up setting") from None

    settings.save()
    return _settings(ctx)


@router.post("/api/choose-folder")
async def choose_folder(request: Request) -> dict:
    """Open the Windows folder picker on the PC."""
    ctx = get_ctx(request)
    path = await asyncio.to_thread(desktop.choose_folder, ctx.settings.shared_dir)
    return {"path": path}


@router.post("/api/open-folder")
async def open_folder(request: Request) -> dict:
    await asyncio.to_thread(desktop.open_in_explorer, get_ctx(request).settings.shared_dir)
    return {"opened": True}


@router.post("/api/restart")
async def restart(request: Request) -> dict:
    ctx = get_ctx(request)
    # Let this response reach the browser first.
    asyncio.get_running_loop().call_later(0.5, ctx.request_restart)
    return {"restarting": True}
