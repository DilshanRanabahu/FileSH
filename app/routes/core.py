"""Page, status, connecting (QR code and PIN), sharing on/off, and live updates."""

import time

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from app.config import STATIC_DIR
from app.context import AppContext, get_ctx
from app.events import Client
from app.security import (
    COOKIE_NAME,
    DEVICE_COOKIE,
    client_ip,
    device_id,
    device_name,
    has_access,
    is_local,
    new_device_id,
    require_access,
    require_local,
)
from app.utils import make_qr_svg

router = APIRouter()

DEVICE_COOKIE_AGE = 365 * 24 * 3600


def grant_access(response: Response, request: Request, ctx: AppContext) -> None:
    """Save the token (and a device ID) in cookies the page's JavaScript can't read."""
    secure = request.url.scheme == "https"
    response.set_cookie(
        COOKIE_NAME, ctx.access.token, httponly=True, samesite="strict", secure=secure, path="/"
    )
    if device_id(request).startswith("ip:"):
        response.set_cookie(
            DEVICE_COOKIE,
            new_device_id(),
            max_age=DEVICE_COOKIE_AGE,
            httponly=True,
            samesite="strict",
            secure=secure,
            path="/",
        )


@router.get("/", include_in_schema=False)
async def index(request: Request, t: str | None = None) -> FileResponse:
    ctx = get_ctx(request)
    response = FileResponse(STATIC_DIR / "index.html", media_type="text/html")
    if t and ctx.access.sharing and ctx.access.is_valid(t):
        grant_access(response, request, ctx)
    return response


@router.get("/api/status", dependencies=[Depends(require_access)])
async def status(request: Request) -> dict:
    ctx = get_ctx(request)
    local = is_local(request)
    return {
        "sharing": ctx.access.sharing,
        "is_pc": local,
        "devices": len(ctx.access.online(ctx.settings.online_timeout, ctx.hub.connected_devices())),
        "public_network": await ctx.public_network() if local else False,
    }


@router.get("/api/devices", dependencies=[Depends(require_local)])
async def devices(request: Request) -> list[dict]:
    ctx = get_ctx(request)
    connected = ctx.hub.connected_devices()
    now = time.monotonic()
    return [
        {
            "name": d.name,
            "ip": d.ip,
            "connected_seconds": int(now - d.first_seen),
            "live": d.id in connected,
        }
        for d in ctx.access.online(ctx.settings.online_timeout, connected)
    ]


@router.get("/api/connect", dependencies=[Depends(require_local)])
async def connect(request: Request) -> dict:
    ctx = get_ctx(request)
    return {
        "address": ctx.network_address(),
        "url": ctx.connect_url(),
        "pin": ctx.access.pin,
        "discovery_url": ctx.discovery_url(),
        "https": ctx.running_https,
    }


@router.get("/api/qr.svg", dependencies=[Depends(require_local)])
async def qr_code(request: Request) -> Response:
    ctx = get_ctx(request)
    url = ctx.connect_url()
    if not ctx.access.sharing or url is None:
        raise HTTPException(409, "Not available")
    return Response(make_qr_svg(url), media_type="image/svg+xml")


class PinBody(BaseModel):
    pin: str


@router.post("/api/pin")
async def enter_pin(request: Request, body: PinBody) -> Response:
    ctx = get_ctx(request)
    if not ctx.access.sharing:
        raise HTTPException(503, "Sharing is stopped")
    pin = "".join(ch for ch in body.pin if ch.isdigit())[:6]
    result = ctx.access.check_pin(client_ip(request), pin)
    if result.blocked_seconds:
        minutes = (result.blocked_seconds + 59) // 60
        unit = "minute" if minutes == 1 else "minutes"
        raise HTTPException(429, f"Too many attempts. Try again in {minutes} {unit}.")
    if not result.ok:
        left = result.attempts_left
        raise HTTPException(
            403, f"Wrong PIN. {left} {'attempt' if left == 1 else 'attempts'} left."
        )
    response = JSONResponse({"ok": True})
    grant_access(response, request, ctx)
    return response


@router.post("/api/stop", dependencies=[Depends(require_local)])
async def stop_sharing(request: Request) -> dict:
    await get_ctx(request).set_sharing(False)
    return {"sharing": False}


@router.post("/api/start", dependencies=[Depends(require_local)])
async def start_sharing(request: Request) -> dict:
    await get_ctx(request).set_sharing(True)
    return {"sharing": True}


@router.websocket("/ws")
async def live(websocket: WebSocket) -> None:
    """Pushes events (files changed, new text, transfer requests) to the browser."""
    ctx = get_ctx(websocket)
    if not has_access(websocket):
        await websocket.close(code=4001)
        return
    await websocket.accept()
    local = is_local(websocket)
    device = device_id(websocket)
    name = device_name(websocket.headers.get("user-agent", ""))
    if not local:
        ctx.access.touch(device, name, client_ip(websocket))
    ctx.hub.add(websocket, Client(device, local))
    if not local:
        await ctx.hub.send({"type": "devices"}, pcs_only=True)
    try:
        while True:
            await websocket.receive_text()  # the page sends "ping" every 25 s
            if not local:
                if not has_access(websocket):
                    await websocket.close(code=4001)
                    break
                ctx.access.touch(device, name, client_ip(websocket))
    except WebSocketDisconnect:
        pass
    finally:
        ctx.hub.remove(websocket)
        if not local:
            await ctx.hub.send({"type": "devices"}, pcs_only=True)
