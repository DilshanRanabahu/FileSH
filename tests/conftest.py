from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import app.context
import app.desktop
from app.config import Settings
from app.main import create_app

BASE_URL = "http://localhost:8000"
ORIGIN = {"Origin": BASE_URL}
PHONE_UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36"}


@pytest.fixture(autouse=True)
def no_desktop_side_effects(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Never start PowerShell, change the registry, or open windows during tests."""
    monkeypatch.setattr(app.context, "is_public_network", lambda: False)
    calls: list[bool] = []
    monkeypatch.setattr(
        app.desktop, "start_with_windows_enabled", lambda: bool(calls and calls[-1])
    )
    monkeypatch.setattr(app.desktop, "set_start_with_windows", calls.append)
    monkeypatch.setattr(app.desktop, "open_in_explorer", lambda path: None)
    monkeypatch.setattr(app.desktop, "choose_folder", lambda initial: None)
    # pytest's temporary folders are inside AppData, which is protected for real use.
    monkeypatch.setattr(app.desktop, "_protected_folders", lambda: [])
    return calls


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    folder = tmp_path / "shared"
    folder.mkdir()
    return folder


@pytest.fixture
def settings(shared: Path, tmp_path: Path) -> Settings:
    # Most tests don't need the "Accept / Reject" step; tests for it switch it on.
    return Settings(
        port=8000,
        shared_dir=shared,
        data_dir=tmp_path / "data",
        open_browser=False,
        ask_before_receiving=False,
    )


@pytest.fixture
def server(settings: Settings) -> FastAPI:
    return create_app(settings)


def make_client(server: FastAPI, ip: str, **headers: str) -> TestClient:
    return TestClient(server, base_url=BASE_URL, headers={**ORIGIN, **headers}, client=(ip, 50000))


@pytest.fixture
def pc(server: FastAPI) -> TestClient:
    """A browser on the PC itself."""
    return make_client(server, "127.0.0.1")


@pytest.fixture
def stranger(server: FastAPI) -> TestClient:
    """Another device on the network that has not scanned the QR code."""
    return make_client(server, "192.168.1.50", **PHONE_UA)


def connect_phone(server: FastAPI, ip: str = "192.168.1.20") -> TestClient:
    """A device that scanned the QR code, so it has the token and device cookies."""
    client = make_client(server, ip, **PHONE_UA)
    response = client.get(f"/?t={server.state.ctx.access.token}")
    assert response.status_code == 200
    return client


@pytest.fixture
def phone(server: FastAPI) -> TestClient:
    return connect_phone(server)


def upload(
    client: TestClient,
    name: str,
    data: bytes = b"hello",
    folder: str = "",
    folders: str = "",
    transfer: str | None = None,
):
    """Upload in two steps, like the browser: start, then send the bytes."""
    start = client.post(
        "/api/uploads",
        json={
            "dir": folder,
            "folders": folders,
            "name": name,
            "size": len(data),
            "transfer": transfer,
        },
    )
    if start.status_code != 200:
        return start
    info = start.json()
    return client.put(f"/api/uploads/{info['id']}", params={"offset": info["offset"]}, content=data)
