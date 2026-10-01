import http.client
import io
import json
import os
import socket
import threading
import time
import tracemalloc
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from PIL import Image
from starlette.testclient import TestClient

from app.config import MB, Settings
from app.main import create_app
from app.utils import PART_PREFIX, PART_SUFFIX, remove_part_files
from tests.conftest import upload


def test_page_loads(phone: TestClient) -> None:
    response = phone.get("/")
    assert response.status_code == 200
    assert "FileSh" in response.text
    assert phone.get("/static/js/main.js").status_code == 200


# ---------- Listing ----------


def test_empty_folder(phone: TestClient) -> None:
    response = phone.get("/api/files")
    assert response.status_code == 200
    assert response.json() == {"path": "", "items": []}


def test_list_folders_first_sorted_by_name(phone: TestClient, shared: Path) -> None:
    (shared / "b.txt").write_text("b")
    (shared / "A.txt").write_text("a")
    (shared / "zeta").mkdir()
    (shared / "Alpha").mkdir()

    items = phone.get("/api/files").json()["items"]
    assert [(i["name"], i["type"]) for i in items] == [
        ("Alpha", "folder"),
        ("zeta", "folder"),
        ("A.txt", "file"),
        ("b.txt", "file"),
    ]
    assert items[2]["size"] == 1


def test_list_subfolder(phone: TestClient, shared: Path) -> None:
    (shared / "Photos" / "2026").mkdir(parents=True)
    (shared / "Photos" / "2026" / "beach.jpg").write_bytes(b"x")

    data = phone.get("/api/files", params={"path": "Photos/2026"}).json()
    assert data["path"] == "Photos/2026"
    assert data["items"][0]["name"] == "beach.jpg"


def test_missing_folder(phone: TestClient) -> None:
    response = phone.get("/api/files", params={"path": "nope"})
    assert response.status_code == 404
    assert response.json() == {"error": "Folder not found"}


def test_modified_time_is_returned(phone: TestClient, shared: Path) -> None:
    (shared / "a.txt").write_text("a")
    modified = phone.get("/api/files").json()["items"][0]["modified"]
    assert abs(modified - time.time()) < 60


# ---------- Upload and download ----------


def test_upload_then_download(phone: TestClient, shared: Path) -> None:
    data = os.urandom(3 * MB + 17)
    response = upload(phone, "photo.jpg", data)
    assert response.status_code == 201
    assert response.json() == {
        "name": "photo.jpg",
        "path": "photo.jpg",
        "size": len(data),
        "done": True,
    }
    assert (shared / "photo.jpg").read_bytes() == data

    download = phone.get("/api/download", params={"path": "photo.jpg"})
    assert download.status_code == 200
    assert download.content == data


def test_download_supports_ranges(phone: TestClient, shared: Path) -> None:
    (shared / "a.bin").write_bytes(b"0123456789")
    response = phone.get("/api/download", params={"path": "a.bin"}, headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"


def test_upload_empty_file(phone: TestClient, shared: Path) -> None:
    assert upload(phone, "empty.txt", b"").status_code == 201
    assert (shared / "empty.txt").read_bytes() == b""


def test_upload_never_overwrites(phone: TestClient, shared: Path) -> None:
    for content in (b"one", b"two", b"three"):
        assert upload(phone, "notes.txt", content).status_code == 201

    assert (shared / "notes.txt").read_bytes() == b"one"
    assert (shared / "notes (1).txt").read_bytes() == b"two"
    assert (shared / "notes (2).txt").read_bytes() == b"three"


def test_upload_into_subfolder(phone: TestClient, shared: Path) -> None:
    (shared / "Docs").mkdir()
    response = upload(phone, "cv.pdf", b"pdf", folder="Docs")
    assert response.status_code == 201
    assert (shared / "Docs" / "cv.pdf").read_bytes() == b"pdf"


def test_upload_into_missing_folder(phone: TestClient) -> None:
    assert upload(phone, "a.txt", folder="missing").status_code == 404


def test_folder_upload_creates_folders(phone: TestClient, shared: Path) -> None:
    assert upload(phone, "a.jpg", b"a", folders="Trip/2026").status_code == 201
    assert upload(phone, "b.jpg", b"b", folders="Trip").status_code == 201
    assert (shared / "Trip" / "2026" / "a.jpg").read_bytes() == b"a"
    assert (shared / "Trip" / "b.jpg").read_bytes() == b"b"


def test_folder_named_like_a_file(phone: TestClient, shared: Path) -> None:
    (shared / "Trip").write_text("I am a file")
    assert upload(phone, "a.jpg", folders="Trip").status_code == 409


def test_unicode_names(phone: TestClient, shared: Path) -> None:
    for name in ("ලිපිය.txt", "கடிதம்.txt", "party 🎉.jpg"):
        assert upload(phone, name).status_code == 201
        assert (shared / name).exists()
        assert phone.get("/api/download", params={"path": name}).status_code == 200


def test_iphone_decomposed_name_is_normalized(phone: TestClient) -> None:
    response = upload(phone, "café.txt")
    assert response.json()["name"] == "café.txt"


def test_upload_leaves_no_part_files(phone: TestClient, shared: Path) -> None:
    upload(phone, "a.txt")
    assert not list(shared.glob(f"{PART_PREFIX}*"))


def test_part_files_are_hidden_and_cleaned(phone: TestClient, shared: Path) -> None:
    part = shared / f"{PART_PREFIX}abc{PART_SUFFIX}"
    part.write_bytes(b"half")
    assert phone.get("/api/files").json()["items"] == []
    assert phone.get("/api/download", params={"path": part.name}).status_code == 404

    assert remove_part_files(shared) == 1
    assert not part.exists()


# ---------- Resume ----------


def _start(client: TestClient, name: str, size: int, **extra) -> dict:
    response = client.post("/api/uploads", json={"name": name, "size": size, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_continues_after_interruption(phone: TestClient, shared: Path) -> None:
    data = os.urandom(5000)
    info = _start(phone, "video.mp4", len(data), modified=123.0)

    # The first attempt only gets half-way.
    first = phone.put(f"/api/uploads/{info['id']}", params={"offset": 0}, content=data[:2000])
    assert first.json() == {"offset": 2000, "done": False}

    # Starting the same file again finds the unfinished upload.
    again = _start(phone, "video.mp4", len(data), modified=123.0)
    assert again == {"id": info["id"], "offset": 2000}
    assert phone.get(f"/api/uploads/{info['id']}").json()["offset"] == 2000

    rest = phone.put(f"/api/uploads/{info['id']}", params={"offset": 2000}, content=data[2000:])
    assert rest.status_code == 201
    assert (shared / "video.mp4").read_bytes() == data


def test_upload_wrong_offset(phone: TestClient) -> None:
    info = _start(phone, "a.bin", 10)
    phone.put(f"/api/uploads/{info['id']}", params={"offset": 0}, content=b"12345")
    response = phone.put(f"/api/uploads/{info['id']}", params={"offset": 2}, content=b"345")
    assert response.status_code == 409
    assert response.json()["offset"] == 5


def test_different_file_does_not_resume(phone: TestClient) -> None:
    first = _start(phone, "a.bin", 10, modified=1.0)
    second = _start(phone, "a.bin", 10, modified=2.0)
    assert first["id"] != second["id"]


def test_cancel_upload_deletes_part_file(phone: TestClient, shared: Path) -> None:
    info = _start(phone, "a.bin", 10)
    phone.put(f"/api/uploads/{info['id']}", params={"offset": 0}, content=b"123")
    assert list(shared.glob(f"{PART_PREFIX}*"))
    assert phone.delete(f"/api/uploads/{info['id']}").status_code == 200
    assert not list(shared.glob(f"{PART_PREFIX}*"))
    assert phone.get(f"/api/uploads/{info['id']}").status_code == 404


# ---------- Folder ZIP ----------


def test_download_folder_as_zip(phone: TestClient, shared: Path) -> None:
    (shared / "Trip" / "2026").mkdir(parents=True)
    (shared / "Trip" / "a.txt").write_text("A")
    (shared / "Trip" / "2026" / "ලිපිය.txt").write_text("B", encoding="utf-8")
    (shared / "Trip" / "empty").mkdir()
    (shared / "Trip" / f"{PART_PREFIX}x{PART_SUFFIX}").write_text("unfinished")

    response = phone.get("/api/download-zip", params={"path": "Trip"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "Trip.zip" in response.headers["content-disposition"]

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.testzip() is None
    assert sorted(archive.namelist()) == ["Trip/2026/ලිපිය.txt", "Trip/a.txt", "Trip/empty/"]
    assert archive.read("Trip/a.txt") == b"A"


def test_zip_of_whole_shared_folder(phone: TestClient, shared: Path) -> None:
    (shared / "a.txt").write_text("A")
    response = phone.get("/api/download-zip")
    assert "Shared.zip" in response.headers["content-disposition"]
    assert zipfile.ZipFile(io.BytesIO(response.content)).namelist() == ["Shared/a.txt"]


# ---------- Preview and thumbnails ----------


def _png(path: Path, size: tuple[int, int] = (400, 300)) -> None:
    Image.new("RGB", size, "red").save(path, "PNG")


def test_preview_image_inline(phone: TestClient, shared: Path) -> None:
    _png(shared / "pic.png")
    response = phone.get("/api/preview", params={"path": "pic.png"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].startswith("inline")


def test_preview_video_supports_seeking(phone: TestClient, shared: Path) -> None:
    (shared / "clip.mp4").write_bytes(b"0" * 1000)
    response = phone.get(
        "/api/preview", params={"path": "clip.mp4"}, headers={"Range": "bytes=0-99"}
    )
    assert response.status_code == 206
    assert response.headers["content-type"] == "video/mp4"


def test_thumbnail(phone: TestClient, shared: Path) -> None:
    _png(shared / "pic.png")
    response = phone.get("/api/thumbnail", params={"path": "pic.png"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    image = Image.open(io.BytesIO(response.content))
    assert max(image.size) <= 160


def test_thumbnail_of_broken_image(phone: TestClient, shared: Path) -> None:
    (shared / "broken.jpg").write_bytes(b"not an image")
    assert phone.get("/api/thumbnail", params={"path": "broken.jpg"}).status_code == 415


def test_no_thumbnail_for_other_types(phone: TestClient, shared: Path) -> None:
    (shared / "a.txt").write_text("a")
    assert phone.get("/api/thumbnail", params={"path": "a.txt"}).status_code == 415


# ---------- Large files ----------


@pytest.fixture
def live_server(shared: Path, tmp_path: Path) -> Iterator[int]:
    """A real Uvicorn server. TestClient keeps request bodies in memory, so it can't be used
    to measure memory."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = Settings(
        port=port, shared_dir=shared, data_dir=tmp_path / "data", open_browser=False
    )
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield port
    server.should_exit = True
    thread.join(timeout=5)


def test_large_upload_and_download_use_little_memory(live_server: int, shared: Path) -> None:
    port = live_server
    size = 256 * MB
    piece = b"x" * (256 * 1024)
    headers = {"Host": f"localhost:{port}", "Origin": f"http://localhost:{port}"}

    def body() -> Iterator[bytes]:
        for _ in range(size // len(piece)):
            yield piece

    tracemalloc.start()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    start = json.dumps({"name": "big.bin", "size": size})
    connection.request(
        "POST", "/api/uploads", body=start, headers={**headers, "Content-Type": "application/json"}
    )
    response = connection.getresponse()
    upload_id = json.loads(response.read())["id"]

    connection.request(
        "PUT",
        f"/api/uploads/{upload_id}?offset=0",
        body=body(),
        headers={**headers, "Content-Length": str(size)},
    )
    response = connection.getresponse()
    response.read()
    assert response.status == 201

    connection.request("GET", "/api/download?path=big.bin", headers=headers)
    response = connection.getresponse()
    received = 0
    while chunk := response.read(1 * MB):
        received += len(chunk)

    connection.request("GET", "/api/download-zip", headers=headers)
    response = connection.getresponse()
    zipped = 0
    while chunk := response.read(1 * MB):
        zipped += len(chunk)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    connection.close()

    assert (shared / "big.bin").stat().st_size == size
    assert received == size
    assert zipped > size
    assert peak < 32 * MB, f"peak memory {peak / MB:.1f} MB"
