"""Everything the routes share: settings, access, live updates, transfers, history."""

import asyncio
import contextlib
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from starlette.requests import HTTPConnection

from app.config import Settings
from app.discovery import Discovery
from app.events import Hub, watch_shared_folder
from app.history import History, Texts
from app.media import trim_thumbnail_cache
from app.security import AccessState
from app.transfers import Transfers, Uploads
from app.utils import get_lan_ip, get_local_ips, is_public_network

logger = logging.getLogger("filesh")

MAINTENANCE_INTERVAL = 30
NETWORK_CHECK_INTERVAL = 60


class AppContext:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # HTTPS can be switched on the Settings page, but it only applies after a restart.
        self.running_https = settings.https
        self.access = AccessState()
        self.hub = Hub()
        self.transfers = Transfers()
        self.uploads = Uploads()
        self.history = History(settings.data_dir / "history.json")
        self.texts = Texts()
        self.discovery = Discovery()
        self.uploads_per_device: dict[str, int] = defaultdict(int)
        self.rename_lock = asyncio.Lock()
        self.thumbnail_slots = asyncio.Semaphore(2)
        self.tls_fingerprint: str | None = None
        self._network_public = False
        self._network_checked_at = 0.0
        self._watch_stop: asyncio.Event | None = None
        self._tasks: list[asyncio.Task] = []
        # Set by the runner and the tray icon.
        self.notify: Callable[[str], None] = lambda message: None
        self.request_restart: Callable[[], None] = lambda: None
        self.on_sharing_changed: Callable[[bool], None] = lambda sharing: None

    # ---------- Addresses ----------

    @property
    def root(self) -> Path:
        return self.settings.shared_dir

    @property
    def scheme(self) -> str:
        return "https" if self.running_https else "http"

    @property
    def thumbnail_dir(self) -> Path:
        return self.settings.data_dir / "thumbnails"

    @property
    def network_port(self) -> int:
        """The port other devices use."""
        return self.settings.https_port if self.running_https else self.settings.port

    def ports(self) -> set[int]:
        return {self.settings.port, self.network_port}

    def hostnames(self) -> set[str]:
        names = get_local_ips()
        if self.discovery.hostname:
            names.add(self.discovery.hostname)
        return names

    def network_address(self) -> str | None:
        ip = get_lan_ip()
        return f"{ip}:{self.network_port}" if ip else None

    def connect_url(self) -> str | None:
        address = self.network_address()
        return f"{self.scheme}://{address}/?t={self.access.token}" if address else None

    def discovery_url(self) -> str | None:
        if not self.discovery.hostname:
            return None
        return f"{self.scheme}://{self.discovery.hostname}:{self.network_port}"

    async def public_network(self) -> bool:
        if time.monotonic() - self._network_checked_at > NETWORK_CHECK_INTERVAL:
            self._network_public = await asyncio.to_thread(is_public_network)
            self._network_checked_at = time.monotonic()
        return self._network_public

    def device_label(self, device_id: str) -> str:
        device = self.access.devices.get(device_id)
        return device.name if device else "This PC"

    # ---------- Sharing ----------

    async def set_sharing(self, on: bool, reason: str | None = None) -> None:
        if on == self.access.sharing:
            return
        if on:
            self.access.start()
        else:
            self.access.stop()
            self.transfers.cancel_all()
            await self.hub.close_remote()
        logger.info("Sharing %s", "started" if on else "stopped")
        await self.hub.send({"type": "sharing", "sharing": on, "reason": reason}, pcs_only=True)
        if reason:
            self.notify(reason)
        self.on_sharing_changed(on)

    def auto_stop_due(self) -> bool:
        minutes = self.settings.auto_stop_minutes
        if not minutes or not self.access.sharing:
            return False
        if self.hub.connected_devices() or self.uploads.active_count():
            self.access.last_activity = time.monotonic()
            return False
        return time.monotonic() - self.access.last_activity > minutes * 60

    # ---------- Background jobs ----------

    async def start_background(self) -> None:
        await self.start_watcher()
        self._tasks.append(asyncio.create_task(self._maintenance()))
        if self.settings.discoverable:
            self._tasks.append(asyncio.create_task(self.start_discovery()))

    async def stop_background(self) -> None:
        await self.stop_watcher()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        await asyncio.to_thread(self.discovery.stop)

    async def start_watcher(self) -> None:
        await self.stop_watcher()
        self._watch_stop = asyncio.Event()
        self._tasks.append(
            asyncio.create_task(watch_shared_folder(self.root, self.hub, self._watch_stop))
        )

    async def stop_watcher(self) -> None:
        if self._watch_stop is not None:
            self._watch_stop.set()
            self._watch_stop = None

    async def start_discovery(self) -> None:
        if self.settings.host.startswith("127."):
            return  # FileSh only listens on this PC, so there is nothing to discover
        ip = get_lan_ip()
        if ip:
            await asyncio.to_thread(self.discovery.start, ip, self.network_port, self.running_https)

    async def stop_discovery(self) -> None:
        await asyncio.to_thread(self.discovery.stop)

    async def change_shared_folder(self, folder: Path) -> None:
        self.uploads.remove_all()
        self.transfers.cancel_all()
        self.settings.shared_dir = folder
        await self.start_watcher()
        await self.hub.files_changed(None)

    async def _maintenance(self) -> None:
        rounds = 0
        while True:
            await asyncio.sleep(MAINTENANCE_INTERVAL)
            try:
                if self.auto_stop_due():
                    minutes = self.settings.auto_stop_minutes
                    await self.set_sharing(
                        False, f"Sharing stopped after {minutes} minutes with no activity"
                    )
                self.transfers.expire()
                self.uploads.remove_stale()
                rounds += 1
                if rounds % 20 == 0:
                    await asyncio.to_thread(trim_thumbnail_cache, self.thumbnail_dir)
            except Exception:
                logger.exception("Maintenance failed")


def get_ctx(connection: HTTPConnection) -> AppContext:
    return connection.app.state.ctx
