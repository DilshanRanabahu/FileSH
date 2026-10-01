"""Transfer history (saved as JSON) and shared text snippets (kept in memory)."""

import asyncio
import json
import logging
import os
import secrets
import time
from collections import deque
from pathlib import Path

logger = logging.getLogger("filesh")

HISTORY_LIMIT = 500
TEXTS_LIMIT = 50


class History:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[dict] = []
        self._lock = asyncio.Lock()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.entries = [e for e in data if isinstance(e, dict)][-HISTORY_LIMIT:]
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logger.warning("History file is damaged; starting a new one")

    def list(self) -> list[dict]:
        return list(reversed(self.entries))

    async def add(self, direction: str, name: str, path: str, size: int, device: str) -> None:
        """`direction` is "received" (into the PC) or "sent" (from the PC to a device)."""
        self.entries.append(
            {
                "time": time.time(),
                "direction": direction,
                "name": name,
                "path": path,
                "size": size,
                "device": device,
            }
        )
        del self.entries[:-HISTORY_LIMIT]
        await self._save()

    async def clear(self) -> None:
        self.entries.clear()
        await self._save()

    async def _save(self) -> None:
        async with self._lock:
            data = json.dumps(self.entries, ensure_ascii=False)
            try:
                await asyncio.to_thread(self._write, data)
            except OSError:
                logger.warning("Could not save history")

    def _write(self, data: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(data, encoding="utf-8")
        os.replace(temp, self.path)


class Texts:
    """The most recent text snippets shared between devices."""

    def __init__(self) -> None:
        self.items: deque[dict] = deque(maxlen=TEXTS_LIMIT)

    def list(self) -> list[dict]:
        return list(reversed(self.items))

    def add(self, text: str, device: str) -> dict:
        item = {"id": secrets.token_urlsafe(8), "text": text, "device": device, "time": time.time()}
        self.items.append(item)
        return item

    def remove(self, item_id: str) -> bool:
        for item in self.items:
            if item["id"] == item_id:
                self.items.remove(item)
                return True
        return False

    def clear(self) -> None:
        self.items.clear()
