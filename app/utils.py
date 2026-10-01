"""Helpers: safe paths, file names, network, and QR codes."""

import io
import os
import re
import socket
import subprocess
import sys
import unicodedata
from pathlib import Path

import qrcode
from qrcode.image.svg import SvgPathImage

MAX_NAME_LENGTH = 200
PART_PREFIX = ".filesh-"
PART_SUFFIX = ".part"

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class UnsafePathError(ValueError):
    """A requested path points outside the shared folder."""


def safe_path(root: Path, relative: str) -> Path:
    """Resolve a path from a request and make sure it stays inside `root`.

    Every path that comes from a request must go through this function (SECURITY.md 2.2).
    """
    if "\x00" in relative:
        raise UnsafePathError(relative)
    rel = relative.replace("\\", "/").strip()
    # Leading "/" covers absolute and UNC paths; ":" covers drive letters and NTFS streams.
    if rel.startswith("/") or ":" in rel:
        raise UnsafePathError(relative)
    parts = [part for part in rel.split("/") if part not in ("", ".")]
    # Windows ignores trailing dots and spaces, so "..", "...", and ".. " all count as "..".
    if any(part.rstrip(". ") == "" for part in parts):
        raise UnsafePathError(relative)

    root = root.resolve()
    # resolve() follows symlinks and junctions, so links pointing outside are caught too.
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root):
        raise UnsafePathError(relative)
    return target


def relative_path(root: Path, target: Path) -> str:
    """The path of `target` inside `root`, with "/" separators ("" for the root)."""
    rel = target.relative_to(root.resolve()).as_posix()
    return "" if rel == "." else rel


def clean_filename(name: str) -> str:
    """Make an uploaded file name safe to save on Windows (SECURITY.md 2.3)."""
    # iPhones send names in decomposed Unicode (NFD); Windows expects NFC.
    name = unicodedata.normalize("NFC", name)
    name = name.replace("\\", "/").split("/")[-1]
    name = _ILLEGAL_CHARS.sub("", name)
    name = name.strip().rstrip(". ")

    if name.split(".")[0].strip().upper() in _RESERVED_NAMES:
        name = f"_{name}"

    if len(name) > MAX_NAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        if dot and stem and len(ext) <= 20:
            name = f"{stem[: MAX_NAME_LENGTH - len(ext) - 1].rstrip('. ')}.{ext}"
        else:
            name = name[:MAX_NAME_LENGTH].rstrip(". ")

    if not name or name.startswith(PART_PREFIX):
        name = f"file{name}" if name else "file"
    return name


MAX_FOLDER_DEPTH = 32


def clean_folders(folders: str) -> str:
    """Clean every folder name of a folder upload, like "Trip/2026" (SECURITY.md 2.3)."""
    parts = [p for p in folders.replace("\\", "/").split("/") if p.strip()]
    if len(parts) > MAX_FOLDER_DEPTH:
        raise UnsafePathError(folders)
    return "/".join(clean_filename(part) for part in parts)


def unique_path(directory: Path, name: str) -> Path:
    """`directory/name`, or `name (1).ext`, `name (2).ext`, ... if it already exists."""
    candidate = directory / name
    stem, ext = Path(name).stem, Path(name).suffix
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = directory / f"{stem} ({counter}){ext}"
        counter += 1
    return candidate


def is_part_file(name: str) -> bool:
    """True for temporary files of uploads in progress."""
    return name.startswith(PART_PREFIX) and name.endswith(PART_SUFFIX)


def remove_part_files(root: Path) -> int:
    """Delete temporary files left behind by uploads that never finished."""
    removed = 0
    for path in root.rglob(f"{PART_PREFIX}*{PART_SUFFIX}"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _usable_ip(ip: str) -> bool:
    return not ip.startswith(("127.", "169.254.", "0."))


def get_lan_ip() -> str | None:
    """The PC's main local network IP address, e.g. 192.168.1.10."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # No packet is sent; this only asks the OS which interface it would use.
            sock.connect(("10.255.255.255", 1))
            ip = sock.getsockname()[0]
            if _usable_ip(ip):
                return ip
    except OSError:
        pass
    return next(iter(sorted(get_local_ips())), None)


def get_local_ips() -> set[str]:
    """All IPv4 addresses of this PC, except loopback and link-local."""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(str(info[4][0]))
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            ips.add(sock.getsockname()[0])
    except OSError:
        pass
    return {ip for ip in ips if _usable_ip(ip)}


def is_public_network() -> bool:
    """True if Windows reports a connected network with the Public profile."""
    if sys.platform != "win32":
        return False
    # Full path, so a program named "powershell" elsewhere on PATH can't be started instead.
    powershell = (
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    try:
        result = subprocess.run(  # noqa: S603 - fixed command, no user input
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-NetConnectionProfile).NetworkCategory -join ','",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "Public" in (part.strip() for part in result.stdout.split(","))


def make_qr_svg(data: str) -> bytes:
    image = qrcode.make(data, image_factory=SvgPathImage, box_size=10, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue()
