"""Attack tests from SECURITY.md section 2. Every one of these must keep passing."""

import logging
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.desktop
from app.config import STATIC_DIR, Settings
from app.main import create_app
from app.security import COOKIE_NAME, PIN_ATTEMPTS
from app.utils import UnsafePathError, clean_filename, clean_folders, safe_path
from tests.conftest import BASE_URL, connect_phone, make_client, upload

# The test client sends "Host: testserver" for WebSockets unless the URL is complete.
WS_URL = "ws://localhost:8000/ws"

# ---------- 2.1 Strangers on the network ----------


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/api/status"),
        ("GET", "/api/files"),
        ("GET", "/api/download?path=a.txt"),
        ("GET", "/api/download-zip"),
        ("GET", "/api/preview?path=a.txt"),
        ("GET", "/api/thumbnail?path=a.txt"),
        ("POST", "/api/uploads"),
        ("GET", "/api/texts"),
        ("POST", "/api/transfers"),
    ],
)
def test_stranger_is_denied(stranger: TestClient, shared: Path, method: str, url: str) -> None:
    (shared / "a.txt").write_text("secret")
    kwargs = {"json": {"name": "a.txt", "size": 1}} if method == "POST" else {}
    response = stranger.request(method, url, **kwargs)
    assert response.status_code == 401
    assert "secret" not in response.text


def test_wrong_token_gives_no_cookie(stranger: TestClient) -> None:
    response = stranger.get("/?t=wrong-token")
    assert COOKIE_NAME not in response.cookies
    assert stranger.get("/api/files").status_code == 401


def test_non_ascii_cookie_is_denied_not_crash(server: FastAPI) -> None:
    client = TestClient(server, base_url=BASE_URL, client=("192.168.1.50", 1))
    response = client.get("/api/files", headers={"Cookie": f"{COOKIE_NAME}=ä".encode()})
    assert response.status_code == 401


def test_token_cookie_flags(server: FastAPI, stranger: TestClient) -> None:
    response = stranger.get(f"/?t={server.state.ctx.access.token}")
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2  # token and device ID
    for cookie in cookies:
        assert "HttpOnly" in cookie
        assert "samesite=strict" in cookie.lower()


def test_new_token_and_pin_on_every_start(settings: Settings) -> None:
    first, second = create_app(settings).state.ctx.access, create_app(settings).state.ctx.access
    assert first.token != second.token
    assert re.fullmatch(r"\d{6}", first.pin)


# ---------- 2.1 PIN ----------


def test_correct_pin_gives_access(server: FastAPI, stranger: TestClient) -> None:
    response = stranger.post("/api/pin", json={"pin": server.state.ctx.access.pin})
    assert response.status_code == 200
    assert stranger.get("/api/files").status_code == 200


def test_pin_with_space_is_accepted(server: FastAPI, stranger: TestClient) -> None:
    pin = server.state.ctx.access.pin
    response = stranger.post("/api/pin", json={"pin": f"{pin[:3]} {pin[3:]}"})
    assert response.status_code == 200


def test_wrong_pins_block_the_device(server: FastAPI, stranger: TestClient) -> None:
    pin = server.state.ctx.access.pin
    wrong = "000000" if pin != "000000" else "111111"
    for attempt in range(PIN_ATTEMPTS - 1):
        response = stranger.post("/api/pin", json={"pin": wrong})
        assert response.status_code == 403
        assert f"{PIN_ATTEMPTS - attempt - 1} attempt" in response.json()["error"]
    assert stranger.post("/api/pin", json={"pin": wrong}).status_code == 429
    # Blocked, even with the right PIN.
    assert stranger.post("/api/pin", json={"pin": pin}).status_code == 429
    assert stranger.get("/api/files").status_code == 401
    # Other devices are not blocked.
    other = make_client(server, "192.168.1.51")
    assert other.post("/api/pin", json={"pin": pin}).status_code == 200


def test_many_wrong_pins_from_many_devices_change_the_pin(server: FastAPI) -> None:
    access = server.state.ctx.access
    old_pin = access.pin
    wrong = "000000" if old_pin != "000000" else "111111"
    for i in range(20):
        make_client(server, f"192.168.1.{100 + i}").post("/api/pin", json={"pin": wrong})
    assert access.pin != old_pin


def test_pin_does_not_work_when_stopped(
    server: FastAPI, pc: TestClient, stranger: TestClient
) -> None:
    pin = server.state.ctx.access.pin
    pc.post("/api/stop")
    assert stranger.post("/api/pin", json={"pin": pin}).status_code == 503


# ---------- 2.2 Path traversal ----------

ATTACKS = [
    "../secret.txt",
    "..\\secret.txt",
    "%2e%2e/secret.txt",
    "photos/../../secret.txt",
    "...",
    ".. /secret.txt",
    "C:\\Windows\\win.ini",
    "C:/Windows/win.ini",
    "/etc/passwd",
    "\\\\server\\share\\file",
    "a.txt:stream",
    "a.txt\x00.jpg",
]


@pytest.fixture
def secret(shared: Path) -> Path:
    path = shared.parent / "secret.txt"
    path.write_text("TOP SECRET")
    (shared / "photos").mkdir()
    return path


def _get_path(client: TestClient, url: str, attack: str):
    # URL-encoded attacks are sent as-is, so the server decodes them itself.
    if "%" in attack:
        return client.get(f"{url}?path={attack}")
    return client.get(url, params={"path": attack})


@pytest.mark.parametrize("endpoint", ["/api/download", "/api/preview", "/api/thumbnail"])
@pytest.mark.parametrize("attack", ATTACKS)
def test_file_traversal_blocked(
    phone: TestClient, secret: Path, endpoint: str, attack: str
) -> None:
    response = _get_path(phone, endpoint, attack)
    assert response.status_code == 403
    assert "TOP SECRET" not in response.text


@pytest.mark.parametrize("endpoint", ["/api/files", "/api/download-zip"])
@pytest.mark.parametrize("attack", ATTACKS)
def test_folder_traversal_blocked(
    phone: TestClient, secret: Path, endpoint: str, attack: str
) -> None:
    response = _get_path(phone, endpoint, attack)
    assert response.status_code == 403
    assert b"TOP SECRET" not in response.content


@pytest.mark.parametrize("attack", ["..", "../..", "C:\\", "/tmp"])
def test_upload_folder_traversal_blocked(phone: TestClient, shared: Path, attack: str) -> None:
    assert upload(phone, "x.txt", folder=attack).status_code == 403
    assert not (shared.parent / "x.txt").exists()


@pytest.mark.parametrize("folders", ["../escape", "..\\escape", "a/../../escape", "C:/escape"])
def test_folder_upload_names_are_cleaned(phone: TestClient, shared: Path, folders: str) -> None:
    assert upload(phone, "x.txt", folders=folders).status_code == 201
    assert not (shared.parent / "escape").exists()
    saved = [p for p in shared.rglob("x.txt")]
    assert len(saved) == 1
    assert saved[0].is_relative_to(shared)


def test_too_deep_folder_upload(phone: TestClient) -> None:
    assert upload(phone, "x.txt", folders="/".join(["a"] * 40)).status_code == 403


def test_symlink_outside_is_blocked(phone: TestClient, shared: Path, secret: Path) -> None:
    try:
        os.symlink(secret, shared / "link.txt")
    except OSError:
        pytest.skip("Creating symlinks needs Developer Mode or admin rights on Windows")
    assert phone.get("/api/download", params={"path": "link.txt"}).status_code == 403
    names = [item["name"] for item in phone.get("/api/files").json()["items"]]
    assert "link.txt" not in names


@pytest.mark.skipif(sys.platform != "win32", reason="Junctions exist only on Windows")
def test_junction_outside_is_blocked(phone: TestClient, shared: Path, secret: Path) -> None:
    import _winapi

    outside = shared.parent / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("TOP SECRET")
    _winapi.CreateJunction(str(outside), str(shared / "junction"))

    names = [item["name"] for item in phone.get("/api/files").json()["items"]]
    assert "junction" not in names
    assert phone.get("/api/files", params={"path": "junction"}).status_code == 403
    response = phone.get("/api/download", params={"path": "junction/private.txt"})
    assert response.status_code == 403
    # The folder ZIP skips the junction too.
    zipped = phone.get("/api/download-zip")
    assert b"TOP SECRET" not in zipped.content
    assert b"private.txt" not in zipped.content


def test_safe_path_allows_normal_paths(shared: Path) -> None:
    (shared / "a" / "b").mkdir(parents=True)
    assert safe_path(shared, "") == shared.resolve()
    assert safe_path(shared, "a/b") == (shared / "a" / "b").resolve()
    assert safe_path(shared, "a\\b") == (shared / "a" / "b").resolve()
    assert safe_path(shared, "./a/./b/") == (shared / "a" / "b").resolve()


@pytest.mark.parametrize("attack", ATTACKS[:2] + ATTACKS[3:])
def test_safe_path_rejects(shared: Path, attack: str) -> None:
    with pytest.raises(UnsafePathError):
        safe_path(shared, attack)


# ---------- 2.3 Dangerous file names ----------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("photo.jpg", "photo.jpg"),
        ("..\\..\\startup\\virus.exe", "virus.exe"),
        ("../../etc/passwd", "passwd"),
        ("CON.txt", "_CON.txt"),
        ("con", "_con"),
        ("nul.tar.gz", "_nul.tar.gz"),
        ("COM1", "_COM1"),
        ("LPT9.doc", "_LPT9.doc"),
        ("CONSOLE.txt", "CONSOLE.txt"),
        ("report.txt:hidden", "report.txthidden"),
        ('a<b>c"d|e?f*g.txt', "abcdefg.txt"),
        ("bad\x00\x1fname.txt", "badname.txt"),
        ("trailing. . .", "trailing"),
        ("  spaced.txt  ", "spaced.txt"),
        ("", "file"),
        ("...", "file"),
        ("<>:", "file"),
        (".filesh-x.part", "file.filesh-x.part"),
    ],
)
def test_clean_filename(name: str, expected: str) -> None:
    assert clean_filename(name) == expected


def test_clean_folders() -> None:
    assert clean_folders("Trip/2026") == "Trip/2026"
    assert clean_folders("../CON/a:b") == "file/_CON/ab"
    assert clean_folders("") == ""


def test_clean_filename_limits_length_and_keeps_extension() -> None:
    cleaned = clean_filename("a" * 300 + ".jpg")
    assert len(cleaned) == 200
    assert cleaned.endswith(".jpg")


def test_dangerous_upload_names_stay_in_shared_folder(phone: TestClient, shared: Path) -> None:
    for name in ("..\\..\\evil.exe", "CON.txt", "report.txt:hidden"):
        assert upload(phone, name).status_code == 201
    saved = sorted(p.name for p in shared.iterdir())
    assert saved == ["_CON.txt", "evil.exe", "report.txthidden"]
    assert not (shared.parent / "evil.exe").exists()


# ---------- 2.4 Bad websites: Host and Origin checks ----------


@pytest.mark.parametrize("host", ["evil.com", "evil.com:8000", "localhost", "localhost:9999", ""])
def test_bad_host_rejected(phone: TestClient, host: str) -> None:
    response = phone.get("/api/files", headers={"Host": host})
    assert response.status_code == 400


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
def test_local_hosts_accepted(pc: TestClient, host: str) -> None:
    assert pc.get("/api/files", headers={"Host": host}).status_code == 200


def test_discovery_name_accepted_only_when_discoverable(settings: Settings) -> None:
    hidden = make_client(create_app(settings), "127.0.0.1")
    assert hidden.get("/api/files", headers={"Host": "filesh.local:8000"}).status_code == 400

    discoverable = create_app(settings)
    discoverable.state.ctx.discovery.hostname = "filesh.local"
    client = make_client(discoverable, "127.0.0.1")
    assert client.get("/api/files", headers={"Host": "filesh.local:8000"}).status_code == 200


@pytest.mark.parametrize("origin", ["http://evil.com", "null", "http://localhost:9999"])
def test_bad_origin_rejected(phone: TestClient, shared: Path, origin: str) -> None:
    response = phone.post(
        "/api/uploads", json={"name": "a.txt", "size": 1}, headers={"Origin": origin}
    )
    assert response.status_code == 403


def test_missing_origin_rejected(server: FastAPI) -> None:
    client = TestClient(server, base_url=BASE_URL, client=("127.0.0.1", 1))
    assert client.post("/api/stop").status_code == 403
    assert server.state.ctx.access.sharing


def test_no_cors_headers(phone: TestClient) -> None:
    response = phone.get("/api/files", headers={"Origin": "http://evil.com"})
    assert "access-control-allow-origin" not in response.headers


# ---------- 2.5 QR code, token, and PIN only on the PC ----------


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/api/connect"),
        ("GET", "/api/qr.svg"),
        ("GET", "/api/devices"),
        ("GET", "/api/transfers"),
        ("GET", "/api/history"),
        ("DELETE", "/api/history"),
        ("GET", "/api/settings"),
        ("POST", "/api/settings"),
        ("POST", "/api/choose-folder"),
        ("POST", "/api/open-folder"),
        ("POST", "/api/restart"),
        ("POST", "/api/stop"),
        ("POST", "/api/start"),
    ],
)
def test_pc_only_routes(phone: TestClient, method: str, url: str) -> None:
    kwargs = {"json": {}} if method == "POST" else {}
    assert phone.request(method, url, **kwargs).status_code == 403


def test_pc_gets_connect_info(pc: TestClient, server: FastAPI, monkeypatch) -> None:
    monkeypatch.setattr("app.context.get_lan_ip", lambda: "192.168.1.10")
    info = pc.get("/api/connect").json()
    access = server.state.ctx.access
    assert info["address"] == "192.168.1.10:8000"
    assert info["url"] == f"http://192.168.1.10:8000/?t={access.token}"
    assert info["pin"] == access.pin
    qr = pc.get("/api/qr.svg")
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/svg+xml"


def test_forwarded_header_does_not_make_device_local(phone: TestClient) -> None:
    headers = {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"}
    assert phone.get("/api/connect", headers=headers).status_code == 403


def test_page_source_has_no_token_or_pin(server: FastAPI, stranger: TestClient) -> None:
    page = stranger.get("/").text
    assert server.state.ctx.access.token not in page
    assert server.state.ctx.access.pin not in page


# ---------- 2.6 Hidden scripts ----------


def test_downloads_are_attachments(phone: TestClient, shared: Path) -> None:
    (shared / "page.html").write_text("<script>alert(1)</script>")
    response = phone.get("/api/download", params={"path": "page.html"})
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-type"] == "application/octet-stream"


@pytest.mark.parametrize("name", ["page.html", "image.svg", "data.xml", "doc.pdf", "a.txt"])
def test_unsafe_types_are_never_previewed(phone: TestClient, shared: Path, name: str) -> None:
    (shared / name).write_text("<script>alert(1)</script>")
    assert phone.get("/api/preview", params={"path": name}).status_code == 415
    assert phone.get("/api/thumbnail", params={"path": name}).status_code == 415


def test_preview_type_comes_from_extension_not_content(phone: TestClient, shared: Path) -> None:
    (shared / "fake.jpg").write_text("<html><script>alert(1)</script></html>")
    response = phone.get("/api/preview", params={"path": "fake.jpg"})
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_script_file_name_is_cleaned(phone: TestClient) -> None:
    response = upload(phone, "<img src=x onerror=alert(1)>.jpg")
    assert "<" not in response.json()["name"]


def _javascript_code() -> str:
    code = []
    for path in sorted((STATIC_DIR / "js").glob("*.js")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip().startswith("//"):
                code.append(line)
    return "\n".join(code)


def test_frontend_never_uses_html_injection() -> None:
    code = _javascript_code()
    for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert unsafe not in code


def test_html_has_no_inline_scripts_or_styles() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "style=" not in html
    assert not re.search(r"\son[a-z]+=", html)


def test_text_links_only_for_http() -> None:
    texts = (STATIC_DIR / "js" / "texts.js").read_text(encoding="utf-8")
    assert 'url.protocol === "http:" || url.protocol === "https:"' in texts
    assert 'rel = "noopener noreferrer"' in texts


# ---------- 2.7 Disk and overload limits ----------


def _client_with(shared: Path, tmp_path: Path, **overrides) -> TestClient:
    settings = Settings(
        port=8000, shared_dir=shared, data_dir=tmp_path / "data", open_browser=False, **overrides
    )
    return make_client(create_app(settings), "127.0.0.1")


def test_file_too_large(shared: Path, tmp_path: Path) -> None:
    client = _client_with(shared, tmp_path, max_file_size=10)
    response = upload(client, "big.bin", b"x" * 11)
    assert response.status_code == 413
    assert not list(shared.iterdir())


def test_not_enough_disk_space(shared: Path, tmp_path: Path) -> None:
    client = _client_with(shared, tmp_path, min_free_space=10**18)
    assert upload(client, "a.txt").status_code == 507


def test_too_many_parallel_uploads(shared: Path, tmp_path: Path) -> None:
    client = _client_with(shared, tmp_path, max_parallel_uploads=0)
    assert upload(client, "a.txt").status_code == 429


def test_body_larger_than_announced(phone: TestClient) -> None:
    info = phone.post("/api/uploads", json={"name": "a.txt", "size": 5}).json()
    response = phone.put(f"/api/uploads/{info['id']}", params={"offset": 0}, content=b"1234567890")
    assert response.status_code == 400


def test_json_body_size_limit(phone: TestClient) -> None:
    response = phone.post(
        "/api/texts", content=b"x" * (3 * 1024 * 1024), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_text_size_limit(phone: TestClient) -> None:
    assert phone.post("/api/texts", json={"text": "x" * 200_000}).status_code == 413
    assert phone.post("/api/texts", json={"text": "   "}).status_code == 400


# ---------- 2.8 Security headers ----------

REQUIRED_HEADERS = {
    "content-security-policy": "frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


@pytest.mark.parametrize("url", ["/", "/static/js/main.js", "/api/files", "/api/nothing"])
def test_security_headers(phone: TestClient, url: str) -> None:
    response = phone.get(url)
    for header, value in REQUIRED_HEADERS.items():
        assert value in response.headers.get(header, ""), header


def test_websocket_only_allowed_to_same_host(phone: TestClient) -> None:
    csp = phone.get("/").headers["content-security-policy"]
    assert "connect-src 'self' ws://localhost:8000 wss://localhost:8000;" in csp


def test_security_headers_on_rejected_requests(phone: TestClient, stranger: TestClient) -> None:
    for response in (stranger.get("/api/files"), phone.get("/", headers={"Host": "evil.com"})):
        for header in REQUIRED_HEADERS:
            assert header in response.headers


# ---------- 2.10 Stop sharing ----------


def test_stop_and_start_sharing(pc: TestClient, phone: TestClient) -> None:
    assert pc.post("/api/stop").status_code == 200
    assert phone.get("/api/files").status_code == 503
    assert pc.get("/api/files").status_code == 200
    assert pc.get("/api/status").json()["sharing"] is False

    assert pc.post("/api/start").status_code == 200
    # The old token no longer works after sharing restarts.
    assert phone.get("/api/files").status_code == 401


def test_device_count(pc: TestClient, phone: TestClient) -> None:
    phone.get("/api/status")
    assert pc.get("/api/status").json()["devices"] == 1
    devices = pc.get("/api/devices").json()
    assert devices[0]["name"] == "Android phone"


def test_auto_stop_after_no_activity(server: FastAPI) -> None:
    ctx = server.state.ctx
    ctx.settings.auto_stop_minutes = 30
    assert not ctx.auto_stop_due()
    ctx.access.last_activity -= 31 * 60
    assert ctx.auto_stop_due()
    ctx.settings.auto_stop_minutes = 0
    assert not ctx.auto_stop_due()


# ---------- 2.11 Errors and logs ----------


def test_errors_do_not_show_paths(phone: TestClient, shared: Path) -> None:
    response = phone.get("/api/download", params={"path": "missing.txt"})
    assert response.status_code == 404
    assert response.json() == {"error": "File not found"}
    assert str(shared) not in response.text


def test_token_is_not_logged(
    server: FastAPI, stranger: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    token = server.state.ctx.access.token
    with caplog.at_level(logging.DEBUG):
        stranger.get(f"/?t={token}")
        stranger.get("/api/files")
    # Only FileSh's own logs; the test client logs its own request URLs.
    server_logs = [r.getMessage() for r in caplog.records if not r.name.startswith("httpx")]
    assert any("GET /" in message for message in server_logs)
    assert not any(token in message for message in server_logs)


def test_api_docs_are_disabled(pc: TestClient) -> None:
    for url in ("/docs", "/redoc", "/openapi.json"):
        assert pc.get(url).status_code == 404


# ---------- 2.15 Accept or reject cannot be bypassed ----------


@pytest.fixture
def asking(server: FastAPI) -> FastAPI:
    server.state.ctx.settings.ask_before_receiving = True
    return server


def _request(client: TestClient, *files: tuple[str, int], folders: str = "") -> dict:
    body = {"files": [{"name": n, "size": s, "folders": folders} for n, s in files]}
    response = client.post("/api/transfers", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_without_approval_is_refused(
    asking: FastAPI, phone: TestClient, shared: Path
) -> None:
    assert upload(phone, "a.txt").status_code == 403
    assert not list(shared.iterdir())


def test_pending_request_cannot_upload(asking: FastAPI, phone: TestClient) -> None:
    request = _request(phone, ("a.txt", 5))
    assert request["status"] == "pending"
    assert upload(phone, "a.txt", transfer=request["id"]).status_code == 403


def test_accepted_files_can_be_uploaded_once(
    asking: FastAPI, phone: TestClient, pc: TestClient, shared: Path
) -> None:
    request = _request(phone, ("a.txt", 5), ("b.txt", 3))
    assert pc.get("/api/transfers").json()[0]["count"] == 2
    decision = pc.post(f"/api/transfers/{request['id']}/decision", json={"accept": True})
    assert decision.json()["status"] == "accepted"

    assert upload(phone, "a.txt", b"hello", transfer=request["id"]).status_code == 201
    # Same file again, a file that wasn't in the request, or a different size: refused.
    assert upload(phone, "a.txt", b"hello", transfer=request["id"]).status_code == 403
    assert upload(phone, "c.txt", b"hey", transfer=request["id"]).status_code == 403
    assert upload(phone, "b.txt", b"hello", transfer=request["id"]).status_code == 403
    assert upload(phone, "b.txt", b"hey", transfer=request["id"]).status_code == 201
    assert sorted(p.name for p in shared.iterdir()) == ["a.txt", "b.txt"]


def test_another_device_cannot_use_an_approval(
    asking: FastAPI, phone: TestClient, pc: TestClient
) -> None:
    request = _request(phone, ("a.txt", 5))
    pc.post(f"/api/transfers/{request['id']}/decision", json={"accept": True})
    other = connect_phone(asking, "192.168.1.21")
    assert upload(other, "a.txt", b"hello", transfer=request["id"]).status_code == 403
    assert other.get(f"/api/transfers/{request['id']}").status_code == 404


def test_rejected_request(asking: FastAPI, phone: TestClient, pc: TestClient) -> None:
    request = _request(phone, ("a.txt", 5))
    pc.post(f"/api/transfers/{request['id']}/decision", json={"accept": False})
    assert phone.get(f"/api/transfers/{request['id']}").json()["status"] == "rejected"
    assert upload(phone, "a.txt", b"hello", transfer=request["id"]).status_code == 403
    # A decision can't be changed afterwards.
    again = pc.post(f"/api/transfers/{request['id']}/decision", json={"accept": True})
    assert again.status_code == 409


def test_phone_cannot_accept_its_own_request(asking: FastAPI, phone: TestClient) -> None:
    request = _request(phone, ("a.txt", 5))
    response = phone.post(f"/api/transfers/{request['id']}/decision", json={"accept": True})
    assert response.status_code == 403


def test_folder_request_matches_cleaned_names(
    asking: FastAPI, phone: TestClient, pc: TestClient, shared: Path
) -> None:
    request = _request(phone, ("CON.txt", 2), folders="../Trip")
    pc.post(f"/api/transfers/{request['id']}/decision", json={"accept": True})
    response = upload(phone, "CON.txt", b"hi", folders="../Trip", transfer=request["id"])
    assert response.status_code == 201
    assert (shared / "file" / "Trip" / "_CON.txt").exists()


def test_too_many_waiting_requests(asking: FastAPI, phone: TestClient) -> None:
    for _ in range(3):
        _request(phone, ("a.txt", 1))
    response = phone.post("/api/transfers", json={"files": [{"name": "a.txt", "size": 1}]})
    assert response.status_code == 429


def test_pc_uploads_need_no_approval(asking: FastAPI, pc: TestClient) -> None:
    assert pc.post("/api/transfers", json={"files": [{"name": "a", "size": 1}]}).json() == {
        "id": None,
        "status": "accepted",
    }
    assert upload(pc, "a.txt").status_code == 201


# ---------- 2.13 Settings ----------


def test_shared_folder_validation(pc: TestClient, tmp_path: Path, monkeypatch) -> None:
    def error(value: str) -> str:
        response = pc.post("/api/settings", json={"shared_dir": value})
        assert response.status_code == 400, value
        return response.json()["error"]

    assert "drive" in error(Path(tmp_path.anchor).as_posix())
    assert "exist" in error(str(tmp_path / "missing"))
    assert "full path" in error("relative/folder")
    assert "user folder" in error(str(Path.home()))
    (tmp_path / "data").mkdir(exist_ok=True)
    assert "settings" in error(str(tmp_path / "data"))
    windows = tmp_path / "Windows"
    (windows / "System32").mkdir(parents=True)
    monkeypatch.setattr(app.desktop, "_protected_folders", lambda: [windows])
    assert "system" in error(str(windows))
    assert "system" in error(str(windows / "System32"))
    # A folder that contains a protected folder is refused too.
    assert "system" in error(str(tmp_path))


def test_change_shared_folder(pc: TestClient, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.txt").write_text("x")
    response = pc.post("/api/settings", json={"shared_dir": str(other)})
    assert response.status_code == 200
    assert response.json()["shared_dir"] == str(other.resolve())
    assert [i["name"] for i in pc.get("/api/files").json()["items"]] == ["x.txt"]


def test_settings_are_saved(pc: TestClient, settings: Settings) -> None:
    pc.post("/api/settings", json={"auto_stop_minutes": 60, "https": True})
    loaded = Settings(data_dir=settings.data_dir)
    loaded.load_saved()
    assert loaded.auto_stop_minutes == 60
    assert loaded.https is True
    assert pc.get("/api/settings").json()["restart_required"] is True


def test_invalid_auto_stop_value(pc: TestClient) -> None:
    assert pc.post("/api/settings", json={"auto_stop_minutes": 7}).status_code == 400


def test_start_with_windows(pc: TestClient, no_desktop_side_effects: list[bool]) -> None:
    pc.post("/api/settings", json={"start_with_windows": True})
    assert no_desktop_side_effects == [True]


# ---------- 2.14 Live updates ----------


def test_websocket_needs_access(server: FastAPI, stranger: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), stranger.websocket_connect(WS_URL) as ws:
        ws.receive_json()


def test_websocket_needs_same_origin(server: FastAPI) -> None:
    phone = connect_phone(server)
    with (
        pytest.raises(WebSocketDisconnect),
        phone.websocket_connect(WS_URL, headers={"Origin": "http://evil.com"}) as ws,
    ):
        ws.receive_json()


def test_websocket_receives_changes(server: FastAPI, phone: TestClient, pc: TestClient) -> None:
    with phone.websocket_connect(WS_URL) as ws:
        upload(pc, "new.txt")
        event = ws.receive_json()
        assert event == {"type": "files", "paths": [""]}
        pc.post("/api/texts", json={"text": "hello"})
        assert ws.receive_json() == {"type": "texts"}


def test_websocket_closed_when_sharing_stops(
    server: FastAPI, phone: TestClient, pc: TestClient
) -> None:
    with phone.websocket_connect(WS_URL) as ws:
        pc.post("/api/stop")
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 4001


def test_pc_gets_transfer_requests_live(asking: FastAPI, phone: TestClient, pc: TestClient) -> None:
    with pc.websocket_connect(WS_URL) as ws:
        _request(phone, ("a.txt", 5))
        event = ws.receive_json()
        assert event["transfer"]["files"] == [{"name": "a.txt", "size": 5}]
        assert event["transfer"]["device"] == "Android phone"


def test_discovery_does_not_announce_secrets(server: FastAPI, monkeypatch) -> None:
    import app.discovery

    announced = {}

    class FakeZeroconf:
        def __init__(self, **kwargs) -> None:
            pass

        def register_service(self, info, allow_name_change: bool) -> None:
            announced["info"] = info

        def close(self) -> None:
            pass

    monkeypatch.setattr(app.discovery, "Zeroconf", FakeZeroconf)
    discovery = app.discovery.Discovery()
    discovery.start("192.168.1.10", 8000, https=False)
    access = server.state.ctx.access
    info = announced["info"]
    text = f"{info.name} {info.server} {info.properties}"
    assert access.token not in text
    assert access.pin not in text
    assert discovery.hostname == "filesh.local"


# ---------- 2.9 HTTPS certificate ----------


def test_certificate_is_made_and_reused(tmp_path: Path) -> None:
    from app.tls import ensure_certificate, fingerprint

    cert, key = ensure_certificate(tmp_path, ["localhost"], ["192.168.1.10"])
    first = fingerprint(cert)
    assert ensure_certificate(tmp_path, ["localhost"], ["192.168.1.10"]) == (cert, key)
    assert fingerprint(cert) == first
    # A new IP address needs a new certificate.
    ensure_certificate(tmp_path, ["localhost"], ["192.168.1.11"])
    assert fingerprint(cert) != first


def test_history_records_transfers(pc: TestClient, phone: TestClient) -> None:
    upload(phone, "a.txt")
    phone.get("/api/download", params={"path": "a.txt"})
    pc.get("/api/download", params={"path": "a.txt"})  # the PC's own downloads aren't listed
    history = pc.get("/api/history").json()
    assert [(e["direction"], e["name"], e["device"]) for e in history] == [
        ("sent", "a.txt", "Android phone"),
        ("received", "a.txt", "Android phone"),
    ]
    assert pc.delete("/api/history").status_code == 200
    assert pc.get("/api/history").json() == []
