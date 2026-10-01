"""Incoming transfer approvals ("Accept / Reject") and resumable uploads."""

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

PENDING_TIMEOUT = 120  # seconds the PC has to answer a request
ACCEPTED_LIFETIME = 24 * 3600  # how long an accepted transfer can be used (resume, retry)
PARTIAL_LIFETIME = 24 * 3600  # unfinished uploads are deleted after this
MAX_PENDING_PER_DEVICE = 3
MAX_PARTIAL_UPLOADS = 1000


@dataclass
class TransferFile:
    folders: str  # cleaned sub-folders for folder uploads, "" for plain files
    name: str  # cleaned file name
    size: int
    done: bool = False


@dataclass
class Transfer:
    id: str
    device_id: str
    device_name: str
    dir: str
    files: list[TransferFile]
    status: str = "pending"  # pending, accepted, rejected, expired, cancelled
    created: float = field(default_factory=time.monotonic)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "device": self.device_name,
            "status": self.status,
            "count": len(self.files),
            "size": self.total_size,
            "files": [
                {"name": f"{f.folders}/{f.name}" if f.folders else f.name, "size": f.size}
                for f in self.files[:5]
            ],
        }


class Transfers:
    def __init__(self) -> None:
        self.items: dict[str, Transfer] = {}

    def create(
        self, device_id: str, device_name: str, dir: str, files: list[TransferFile]
    ) -> Transfer:
        self.expire()
        pending = [
            t for t in self.items.values() if t.device_id == device_id and t.status == "pending"
        ]
        if len(pending) >= MAX_PENDING_PER_DEVICE:
            raise ValueError("Too many requests waiting for an answer")
        transfer = Transfer(secrets.token_urlsafe(16), device_id, device_name, dir, files)
        self.items[transfer.id] = transfer
        return transfer

    def get(self, transfer_id: str, device_id: str | None = None) -> Transfer | None:
        self.expire()
        transfer = self.items.get(transfer_id)
        if transfer is None or (device_id is not None and transfer.device_id != device_id):
            return None
        return transfer

    def pending(self) -> list[Transfer]:
        self.expire()
        return [t for t in self.items.values() if t.status == "pending"]

    def find_file(
        self, transfer_id: str, device_id: str, dir: str, folders: str, name: str, size: int
    ) -> TransferFile | None:
        """The accepted, not yet finished file that matches exactly, for this device only."""
        transfer = self.get(transfer_id, device_id)
        if transfer is None or transfer.status != "accepted" or transfer.dir != dir:
            return None
        for file in transfer.files:
            if not file.done and (file.folders, file.name, file.size) == (folders, name, size):
                return file
        return None

    def cancel_all(self) -> None:
        for transfer in self.items.values():
            if transfer.status in ("pending", "accepted"):
                transfer.status = "cancelled"

    def expire(self) -> None:
        now = time.monotonic()
        for transfer_id, transfer in list(self.items.items()):
            age = now - transfer.created
            if transfer.status == "pending" and age > PENDING_TIMEOUT:
                transfer.status = "expired"
            elif age > ACCEPTED_LIFETIME:
                del self.items[transfer_id]


@dataclass
class PartialUpload:
    id: str
    device_id: str
    key: tuple
    directory: Path
    name: str
    size: int
    part: Path
    offset: int = 0
    transfer_file: TransferFile | None = None
    updated: float = field(default_factory=time.monotonic)
    # Held while bytes are being written, so only one request writes at a time.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def active(self) -> bool:
        return self.lock.locked()


class Uploads:
    """Unfinished uploads. An upload that was cut off continues from its last byte."""

    def __init__(self) -> None:
        self.items: dict[str, PartialUpload] = {}

    def find(self, device_id: str, key: tuple) -> PartialUpload | None:
        for upload in self.items.values():
            if upload.device_id == device_id and upload.key == key:
                return upload
        return None

    def get(self, upload_id: str, device_id: str) -> PartialUpload | None:
        upload = self.items.get(upload_id)
        if upload is None or upload.device_id != device_id:
            return None
        return upload

    def add(self, upload: PartialUpload) -> None:
        if len(self.items) >= MAX_PARTIAL_UPLOADS:
            raise ValueError("Too many unfinished uploads")
        self.items[upload.id] = upload

    def remove(self, upload: PartialUpload, delete_file: bool = True) -> None:
        self.items.pop(upload.id, None)
        if delete_file:
            upload.part.unlink(missing_ok=True)

    def active_count(self) -> int:
        return sum(1 for u in self.items.values() if u.active)

    def remove_stale(self) -> int:
        cutoff = time.monotonic() - PARTIAL_LIFETIME
        stale = [u for u in self.items.values() if not u.active and u.updated < cutoff]
        for upload in stale:
            self.remove(upload)
        return len(stale)

    def remove_all(self) -> None:
        for upload in list(self.items.values()):
            if not upload.active:
                self.remove(upload)
