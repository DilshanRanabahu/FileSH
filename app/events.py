"""Live updates: WebSocket connections and the shared-folder watcher."""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path

from fastapi import WebSocket
from watchfiles import Change, awatch

from app.utils import is_part_file, relative_path

logger = logging.getLogger("filesh")

# Above this many changed folders in one batch, clients just reload whatever they show.
MAX_CHANGED_PATHS = 50


@dataclass
class Client:
    device_id: str
    is_pc: bool


class Hub:
    """Sends events to connected browsers."""

    def __init__(self) -> None:
        self.clients: dict[WebSocket, Client] = {}

    def add(self, websocket: WebSocket, client: Client) -> None:
        self.clients[websocket] = client

    def remove(self, websocket: WebSocket) -> None:
        self.clients.pop(websocket, None)

    def connected_devices(self) -> set[str]:
        return {c.device_id for c in self.clients.values() if not c.is_pc}

    async def send(
        self, event: dict, *, pcs_only: bool = False, device_id: str | None = None
    ) -> None:
        for websocket, client in list(self.clients.items()):
            if pcs_only and not client.is_pc:
                continue
            if device_id is not None and client.device_id != device_id:
                continue
            try:
                await websocket.send_json(event)
            except Exception:  # noqa: BLE001 - a broken connection must not stop the others
                self.remove(websocket)

    async def close_remote(self) -> None:
        """Disconnect every device except the PC (sharing was stopped)."""
        for websocket, client in list(self.clients.items()):
            if not client.is_pc:
                self.remove(websocket)
                with contextlib.suppress(Exception):
                    await websocket.close(code=4001)

    async def files_changed(self, paths: set[str] | None) -> None:
        """`paths` are the folders that changed; None means "reload everything"."""
        if paths is not None and len(paths) > MAX_CHANGED_PATHS:
            paths = None
        await self.send({"type": "files", "paths": None if paths is None else sorted(paths)})


def _not_part_file(change: Change, path: str) -> bool:
    return not is_part_file(Path(path).name)


async def watch_shared_folder(root: Path, hub: Hub, stop: asyncio.Event) -> None:
    """Tell browsers when files change in the shared folder, also changes made in Explorer."""
    try:
        async for changes in awatch(
            root, stop_event=stop, watch_filter=_not_part_file, debounce=400, recursive=True
        ):
            folders: set[str] = set()
            for _, changed in changes:
                parent = Path(changed).parent
                try:
                    folders.add(relative_path(root, parent))
                except ValueError:
                    continue
            if folders:
                await hub.files_changed(folders)
    except Exception as exc:  # noqa: BLE001 - the app keeps working with polling
        logger.warning("Folder watcher stopped: %s", type(exc).__name__)
