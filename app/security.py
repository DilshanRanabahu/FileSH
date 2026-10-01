"""Access control and request checks. See SECURITY.md for the reasons behind each rule."""

import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("filesh")

COOKIE_NAME = "filesh_token"
DEVICE_COOKIE = "filesh_device"
PC_DEVICE = "pc"
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Largest request body other than file data (e.g. a request to send 10,000 files).
# Checked before the body is read, so a huge request can't fill memory (SECURITY.md 2.7).
MAX_BODY = 2 * 1024 * 1024

PIN_ATTEMPTS = 5
PIN_BLOCK_SECONDS = 5 * 60
# After this many wrong PINs from all devices together, a new PIN is made.
PIN_TOTAL_FAILURES = 20

# SECURITY.md 2.8. Live updates may only connect back to the same host.
CSP = (
    "default-src 'self'; connect-src 'self' {ws}; img-src 'self' data: blob:; "
    "media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)


def content_security_policy(host: str | None) -> tuple[bytes, bytes]:
    ws = f"ws://{host} wss://{host}" if host else ""
    return b"content-security-policy", CSP.format(ws=ws).replace("  ", " ").encode()


SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
]


def device_name(user_agent: str) -> str:
    """A friendly name like "iPhone" or "Android phone" from the browser's User-Agent."""
    ua = user_agent or ""
    if "iPhone" in ua:
        return "iPhone"
    if "iPad" in ua:
        return "iPad"
    if "Android" in ua:
        return "Android phone" if "Mobile" in ua else "Android tablet"
    if "CrOS" in ua:
        return "Chromebook"
    if "Windows" in ua:
        return "Windows PC"
    if "Macintosh" in ua:
        return "Mac"
    if "Linux" in ua:
        return "Linux PC"
    return "Device"


@dataclass
class Device:
    id: str
    name: str
    ip: str
    first_seen: float
    last_seen: float


@dataclass
class PinResult:
    ok: bool
    attempts_left: int = 0
    blocked_seconds: int = 0


class AccessState:
    """The access token and PIN, sharing on/off, and recently seen devices."""

    def __init__(self) -> None:
        self.sharing = True
        self.devices: dict[str, Device] = {}
        self.last_activity = time.monotonic()
        self._new_secrets()

    def _new_secrets(self) -> None:
        self.token = secrets.token_urlsafe(32)
        self.pin = f"{secrets.randbelow(10**6):06d}"
        self._pin_failures: dict[str, int] = {}
        self._blocked_until: dict[str, float] = {}
        self._total_failures = 0

    def is_valid(self, value: str | None) -> bool:
        if not value:
            return False
        return secrets.compare_digest(value.encode(), self.token.encode())

    def check_pin(self, ip: str, pin: str) -> PinResult:
        now = time.monotonic()
        blocked_until = self._blocked_until.get(ip, 0)
        if blocked_until > now:
            return PinResult(False, blocked_seconds=int(blocked_until - now) + 1)
        if secrets.compare_digest(pin.encode(), self.pin.encode()):
            self._pin_failures.pop(ip, None)
            return PinResult(True)

        failures = self._pin_failures.get(ip, 0) + 1
        self._total_failures += 1
        if self._total_failures >= PIN_TOTAL_FAILURES:
            # Many wrong guesses from different addresses: make a new PIN.
            logger.warning("Too many wrong PINs; a new PIN was made")
            self.pin = f"{secrets.randbelow(10**6):06d}"
            self._total_failures = 0
        if failures >= PIN_ATTEMPTS:
            self._pin_failures.pop(ip, None)
            self._blocked_until[ip] = now + PIN_BLOCK_SECONDS
            logger.warning("Blocked %s for 5 minutes after %d wrong PINs", ip, failures)
            return PinResult(False, blocked_seconds=PIN_BLOCK_SECONDS)
        self._pin_failures[ip] = failures
        return PinResult(False, attempts_left=PIN_ATTEMPTS - failures)

    def stop(self) -> None:
        self.sharing = False
        self._new_secrets()
        self.devices.clear()

    def start(self) -> None:
        self.sharing = True
        self._new_secrets()
        self.last_activity = time.monotonic()

    def touch(self, device_id: str, name: str, ip: str) -> None:
        now = time.monotonic()
        device = self.devices.get(device_id)
        if device is None:
            self.devices[device_id] = Device(device_id, name, ip, now, now)
        else:
            device.last_seen, device.ip = now, ip
        self.last_activity = now

    def online(self, timeout: float, connected: set[str] = frozenset()) -> list[Device]:
        """Devices seen within `timeout` seconds, or with a live connection open."""
        cutoff = time.monotonic() - timeout
        return [d for d in self.devices.values() if d.last_seen >= cutoff or d.id in connected]


def is_local(connection: HTTPConnection) -> bool:
    """True only for requests from the PC itself. Never uses forwarded headers."""
    return connection.client is not None and connection.client.host in LOOPBACK_HOSTS


def client_ip(connection: HTTPConnection) -> str:
    return connection.client.host if connection.client else "-"


_DEVICE_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")


def new_device_id() -> str:
    return secrets.token_urlsafe(24)


def device_id(connection: HTTPConnection) -> str:
    if is_local(connection):
        return PC_DEVICE
    value = connection.cookies.get(DEVICE_COOKIE, "")
    if _DEVICE_ID.fullmatch(value):
        return value
    # Missing or invalid device cookie: fall back to the IP address.
    return f"ip:{client_ip(connection)}"


def has_access(connection: HTTPConnection) -> bool:
    if is_local(connection):
        return True
    access: AccessState = connection.app.state.ctx.access
    return access.sharing and access.is_valid(connection.cookies.get(COOKIE_NAME))


def require_access(request: Request) -> None:
    """Allow the PC itself, or another device holding a valid token cookie."""
    if is_local(request):
        return
    access: AccessState = request.app.state.ctx.access
    if not access.sharing:
        raise HTTPException(503, "Sharing is stopped")
    if not access.is_valid(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(401, "Access denied. Scan the QR code on your PC again.")
    access.touch(
        device_id(request), device_name(request.headers.get("user-agent", "")), client_ip(request)
    )


def require_local(request: Request) -> None:
    if not is_local(request):
        raise HTTPException(403, "Only available on the PC")


def _is_upload_data(method: str, path: str) -> bool:
    """File bytes are streamed to disk, so only they may be larger than MAX_BODY."""
    return method == "PUT" and path.startswith("/api/uploads/")


class SecurityMiddleware:
    """Host check, Origin check, security headers, and access log without query strings."""

    def __init__(
        self, app: ASGIApp, ports: Callable[[], set[int]], hostnames: Callable[[], set[str]]
    ) -> None:
        self.app = app
        self.ports = ports
        self.hostnames = hostnames
        self._names: set[str] = set()
        self._names_checked_at = 0.0

    def _host_allowed(self, host: str) -> bool:
        name, sep, port = host.rpartition(":")
        if not sep or not port.isdigit() or int(port) not in self.ports():
            return False
        name = name.lower()
        if name in LOCAL_HOSTNAMES:
            return True
        # The LAN IP can change (DHCP), so refresh the list on a miss, at most every 10 s.
        if name not in self._names and time.monotonic() - self._names_checked_at > 10:
            self._names = self.hostnames()
            self._names_checked_at = time.monotonic()
        return name in self._names

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        client = scope["client"][0] if scope.get("client") else "-"
        path = scope["path"]

        if scope["type"] == "websocket":
            # Browsers always send Origin on WebSockets; it must be this site (SECURITY.md 2.4).
            http_scheme = "https" if scope.get("scheme") == "wss" else "http"
            if not self._host_allowed(host) or headers.get("origin") != f"{http_scheme}://{host}":
                await send({"type": "websocket.close", "code": 4003})
                self._log(client, "WS", path, 403)
                return
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        if not self._host_allowed(host):
            await self._reject(send, 400, "Invalid host")
            self._log(client, method, path, 400)
            return
        if method not in SAFE_METHODS and headers.get("origin") != f"{scope['scheme']}://{host}":
            await self._reject(send, 403, "Request blocked")
            self._log(client, method, path, 403)
            return
        if method not in SAFE_METHODS and not _is_upload_data(method, path):
            length = headers.get("content-length", "")
            if not length.isdigit() and "transfer-encoding" in headers:
                await self._reject(send, 411, "Request size is missing")
                self._log(client, method, path, 411)
                return
            if length.isdigit() and int(length) > MAX_BODY:
                await self._reject(send, 413, "Request is too large")
                self._log(client, method, path, 413)
                return

        status = 0
        headers_to_add = [content_security_policy(host), *SECURITY_HEADERS]

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = list(message.get("headers", [])) + headers_to_add
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            self._log(client, method, path, status)

    @staticmethod
    def _log(client: str, method: str, path: str, status: int) -> None:
        # Only the path is logged, never the query string (it can hold the token).
        logger.info("%s %s %s %s", client, method, path, status)

    @staticmethod
    async def _reject(send: Send, status: int, error: str) -> None:
        body = json.dumps({"error": error}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    content_security_policy(None),
                    *SECURITY_HEADERS,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
