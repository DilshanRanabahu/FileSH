"""Things that happen on the PC desktop: folder picker, Explorer, start with Windows."""

import contextlib
import logging
import os
import sys
import tempfile
from pathlib import Path

from app.config import FROZEN, PROJECT_DIR

logger = logging.getLogger("filesh")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "FileSh"


class FolderError(ValueError):
    """The chosen folder can't be shared."""


def _protected_folders() -> list[Path]:
    """Folders that must never be shared, because they hold system or private files."""
    names = ("SYSTEMROOT", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "APPDATA")
    folders = [Path(os.environ[n]) for n in names if os.environ.get(n)]
    if os.environ.get("LOCALAPPDATA"):
        folders.append(Path(os.environ["LOCALAPPDATA"]))
    return [f.resolve() for f in folders]


def validate_shared_folder(value: str, data_dir: Path) -> Path:
    """Check a folder chosen on the Settings page (SECURITY.md 2.13)."""
    if not value.strip():
        raise FolderError("Choose a folder")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise FolderError("Use a full path, like D:\\Share")
    path = path.resolve()
    if not path.is_dir():
        raise FolderError("This folder doesn't exist")
    if path.parent == path:
        raise FolderError("A whole drive can't be shared. Choose a folder inside it.")
    if path == Path.home().resolve():
        raise FolderError("Your whole user folder can't be shared. Choose a folder inside it.")
    for protected in _protected_folders():
        if path == protected or path.is_relative_to(protected) or protected.is_relative_to(path):
            raise FolderError("This folder holds system files and can't be shared")
    data_dir = data_dir.resolve()
    if path == data_dir or path.is_relative_to(data_dir) or data_dir.is_relative_to(path):
        raise FolderError("This folder holds FileSh's own settings and can't be shared")
    try:
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError:
        raise FolderError("FileSh can't save files in this folder") from None
    return path


def choose_folder(initial: Path) -> str | None:
    """Show the Windows folder picker on the PC. Returns None if cancelled."""
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:
        return None
    root = tkinter.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(
            parent=root, initialdir=str(initial), title="Choose the FileSh shared folder"
        )
    finally:
        root.destroy()
    return str(Path(chosen)) if chosen else None


def open_in_explorer(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opens a folder the PC owner chose


def launch_command() -> str:
    """The command Windows runs at sign-in: no console window, no browser."""
    if FROZEN:
        return f'"{sys.executable}" --minimized'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{PROJECT_DIR / "FileSh.pyw"}" --minimized'


def start_with_windows_supported() -> bool:
    return sys.platform == "win32"


def start_with_windows_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
        return True
    except OSError:
        return False


def set_start_with_windows(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, RUN_VALUE)
