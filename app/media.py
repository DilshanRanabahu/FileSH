"""Folder ZIPs, previews, and thumbnails."""

import hashlib
import io
import os
import warnings
import zipfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps

from app.config import MB
from app.utils import is_part_file

# Only these types are shown inside the browser; everything else is downloaded (SECURITY.md 2.6).
# The type always comes from this list, never from the file's content.
PREVIEW_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
}
THUMBNAIL_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
THUMBNAIL_SIZE = 160
MAX_THUMBNAIL_SOURCE = 50 * MB
MAX_THUMBNAIL_PIXELS = 50_000_000
MAX_CACHED_THUMBNAILS = 5000


def attachment(filename: str, inline: bool = False) -> str:
    """A Content-Disposition header value that works with any Unicode file name."""
    kind = "inline" if inline else "attachment"
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=utf-8''{quote(filename)}"


# ---------- Folder ZIP ----------


class _Sink(io.RawIOBase):
    """A write-only stream that collects ZIP bytes until they are sent."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.position = 0

    def writable(self) -> bool:
        return True

    def write(self, data: bytes) -> int:  # type: ignore[override]
        self.buffer += data
        self.position += len(data)
        return len(data)

    def tell(self) -> int:
        return self.position

    def take(self) -> bytes:
        data = bytes(self.buffer)
        self.buffer.clear()
        return data


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _walk(directory: Path, prefix: str) -> Iterator[tuple[Path, str, bool]]:
    """(path, name inside the ZIP, is_folder). Links and unfinished uploads are skipped."""
    for current, dirnames, filenames in os.walk(directory):
        current_path = Path(current)
        # Never follow links or junctions out of the shared folder (SECURITY.md 2.2).
        dirnames[:] = sorted(d for d in dirnames if not _is_link(current_path / d))
        rel = current_path.relative_to(directory).as_posix()
        base = prefix if rel == "." else f"{prefix}/{rel}"
        if not dirnames and not filenames:
            yield current_path, f"{base}/", True
        for name in sorted(filenames):
            path = current_path / name
            if not is_part_file(name) and not _is_link(path):
                yield path, f"{base}/{name}", False


def zip_folder(directory: Path, name: str, chunk_size: int = MB) -> Iterator[bytes]:
    """Stream a folder as a ZIP, piece by piece, without making the ZIP on disk first.

    Files are stored without compression: photos and videos are already compressed, and
    this keeps the PC fast.
    """
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path, arcname, is_folder in _walk(directory, name):
            if is_folder:
                archive.mkdir(arcname.rstrip("/"))
                continue
            try:
                source = path.open("rb")
            except OSError:
                continue  # locked or removed while zipping
            with source:
                info = zipfile.ZipInfo.from_file(path, arcname, strict_timestamps=False)
                info.compress_type = zipfile.ZIP_STORED
                with archive.open(info, "w", force_zip64=info.file_size > 1 * 1024 * MB) as dest:
                    while chunk := source.read(chunk_size):
                        dest.write(chunk)
                        if len(sink.buffer) >= chunk_size:
                            yield sink.take()
            if sink.buffer:
                yield sink.take()
    yield sink.take()


# ---------- Thumbnails ----------


def thumbnail_path(cache_dir: Path, source: Path) -> Path:
    info = source.stat()
    key = f"{source}|{info.st_size}|{info.st_mtime_ns}".encode()
    return cache_dir / f"{hashlib.sha256(key).hexdigest()[:32]}.jpg"


def make_thumbnail(source: Path, target: Path) -> bool:
    """Save a small JPEG of an image. False if the image can't be read safely."""
    if source.stat().st_size > MAX_THUMBNAIL_SOURCE:
        return False
    try:
        with warnings.catch_warnings():
            # Treat huge images ("decompression bombs") as errors, not warnings.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = MAX_THUMBNAIL_PIXELS
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
                if image.mode != "RGB":
                    image = image.convert("RGB")
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_suffix(".tmp")
                image.save(temp, "JPEG", quality=80)
                os.replace(temp, target)
        return True
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return False


def trim_thumbnail_cache(cache_dir: Path) -> None:
    try:
        files = sorted(cache_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for path in files[: max(0, len(files) - MAX_CACHED_THUMBNAILS)]:
        path.unlink(missing_ok=True)
