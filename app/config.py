"""FileSh settings. Every configurable value lives here."""

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("filesh")

APP_NAME = "FileSh"
VERSION = "1.0.0"

FROZEN = bool(getattr(sys, "frozen", False))  # running as the PyInstaller .exe
PROJECT_DIR = Path(__file__).resolve().parent.parent
# The web page. In the .exe it is unpacked to the same place next to this file.
STATIC_DIR = Path(__file__).resolve().parent / "static"

KB = 1024
MB = 1024 * KB
GB = 1024 * MB

AUTO_STOP_CHOICES = (0, 15, 30, 60, 120)


def default_shared_dir() -> Path:
    if "FILESH_SHARED_DIR" in os.environ:
        return Path(os.environ["FILESH_SHARED_DIR"])
    return Path.home() / "FileSh" if FROZEN else PROJECT_DIR / "shared"


def default_data_dir() -> Path:
    """Settings, history, thumbnails, and the HTTPS certificate. Never inside the shared folder."""
    if "FILESH_DATA_DIR" in os.environ:
        return Path(os.environ["FILESH_DATA_DIR"])
    base = os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share"
    return Path(base) / APP_NAME


@dataclass
class Settings:
    port: int = int(os.environ.get("FILESH_PORT", "8000"))
    # All network interfaces, so phones can connect. "127.0.0.1" keeps FileSh on this PC only.
    host: str = os.environ.get("FILESH_HOST", "0.0.0.0")  # noqa: S104
    shared_dir: Path = field(default_factory=default_shared_dir)
    data_dir: Path = field(default_factory=default_data_dir)
    max_file_size: int = 20 * GB
    min_free_space: int = 1 * GB
    max_parallel_uploads: int = 3
    chunk_size: int = 1 * MB
    max_text_length: int = 100 * KB
    # A device counts as "online" if it made a request within this many seconds.
    online_timeout: int = 60
    open_browser: bool = True

    # Saved settings, changed on the Settings page.
    ask_before_receiving: bool = True
    auto_stop_minutes: int = 30
    https: bool = False
    discoverable: bool = True

    SAVED_FIELDS = (
        "shared_dir",
        "ask_before_receiving",
        "auto_stop_minutes",
        "https",
        "discoverable",
    )

    def __post_init__(self) -> None:
        self.shared_dir = Path(self.shared_dir).resolve()
        self.data_dir = Path(self.data_dir).resolve()

    @property
    def https_port(self) -> int:
        """With HTTPS on, other devices connect here. The PC's own page stays on plain HTTP
        at `port` (localhost only), so the PC browser shows no certificate warning."""
        return self.port + 1

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    def load_saved(self) -> None:
        try:
            saved = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            logger.warning("Settings file is damaged; using defaults")
            return
        if isinstance(saved.get("shared_dir"), str) and Path(saved["shared_dir"]).is_dir():
            self.shared_dir = Path(saved["shared_dir"]).resolve()
        for name in ("ask_before_receiving", "https", "discoverable"):
            if isinstance(saved.get(name), bool):
                setattr(self, name, saved[name])
        if saved.get("auto_stop_minutes") in AUTO_STOP_CHOICES:
            self.auto_stop_minutes = saved["auto_stop_minutes"]

    def save(self) -> None:
        data = {name: getattr(self, name) for name in self.SAVED_FIELDS}
        data["shared_dir"] = str(self.shared_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temp = self.settings_file.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp, self.settings_file)
