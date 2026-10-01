"""Starts FileSh: the web server, the tray icon, and restarts after settings changes."""

import argparse
import asyncio
import json
import logging
import socket
import sys
import threading
import urllib.request
import webbrowser
from collections.abc import Callable, Coroutine
from pathlib import Path

import uvicorn

from app.config import Settings
from app.discovery import HOSTNAME
from app.main import create_app
from app.tls import ensure_certificate, fingerprint
from app.utils import get_lan_ip, get_local_ips, is_public_network, remove_part_files

logger = logging.getLogger("filesh")

MAX_LOG_SIZE = 5 * 1024 * 1024


class ServerRunner:
    """Runs the web server in its own thread and restarts it when asked."""

    def __init__(self, settings: Settings, open_browser: bool) -> None:
        self.settings = settings
        self.open_browser = open_browser
        self.ctx = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._servers: list[uvicorn.Server] = []
        self._restart = False
        self._quit = False
        self.notify: Callable[[str], None] = lambda message: logger.info("%s", message)
        self.on_sharing_changed: Callable[[bool], None] = lambda sharing: None

    @property
    def local_url(self) -> str:
        return f"http://localhost:{self.settings.port}"

    def run(self) -> None:
        first = True
        while True:
            self._restart = False
            asyncio.run(self._serve(first))
            first = False
            if self._quit or not self._restart:
                break
            logger.info("Restarting FileSh")

    async def _serve(self, first: bool) -> None:
        self.loop = asyncio.get_running_loop()
        settings = self.settings
        app = create_app(settings)
        ctx = app.state.ctx
        ctx.notify = lambda message: self.notify(message)
        ctx.request_restart = self.restart
        ctx.on_sharing_changed = lambda sharing: self.on_sharing_changed(sharing)
        self.ctx = ctx

        common = {"access_log": False, "log_level": "warning", "ws_ping_interval": 20.0}
        if settings.https:
            ips = sorted(get_local_ips() | {"127.0.0.1"})
            cert, key = ensure_certificate(settings.data_dir / "tls", ["localhost", HOSTNAME], ips)
            ctx.tls_fingerprint = fingerprint(cert)
            configs = [
                # Other devices connect here. Access is protected by the token.
                uvicorn.Config(
                    app,
                    host=settings.host,
                    port=settings.https_port,
                    ssl_certfile=str(cert),
                    ssl_keyfile=str(key),
                    **common,
                ),
                # The PC's own page: plain HTTP, only reachable from this PC.
                uvicorn.Config(app, host="127.0.0.1", port=settings.port, lifespan="off", **common),
            ]
        else:
            configs = [uvicorn.Config(app, host=settings.host, port=settings.port, **common)]

        self._servers = [uvicorn.Server(config) for config in configs]
        self._print_banner(ctx)
        if first and self.open_browser:
            self.loop.call_later(1.5, webbrowser.open, self.local_url)
        await asyncio.gather(*(server.serve() for server in self._servers))

    def _stop_servers(self) -> None:
        for server in self._servers:
            server.should_exit = True

    def restart(self) -> None:
        """Called inside the server's event loop."""
        self._restart = True
        self._stop_servers()

    def quit(self) -> None:
        """Called from another thread (tray menu or Ctrl+C)."""
        self._quit = True
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._stop_servers)

    def submit(self, coroutine: Coroutine) -> None:
        """Run a coroutine in the server's event loop from another thread."""
        if self.loop is not None and not self.loop.is_closed():
            asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        else:
            coroutine.close()

    def _print_banner(self, ctx) -> None:
        address = ctx.network_address()
        network = f"{ctx.scheme}://{address}" if address else "no network found"
        print("\n  FileSh is running")
        print(f"  On this PC:     {self.local_url}")
        print(f"  Network:        {network}")
        print(f"  Shared folder:  {self.settings.shared_dir}")
        print("  To connect a phone, scan the QR code on the PC page.")
        if is_public_network():
            print("\n  WARNING: Windows reports your network as Public.")
            print(
                "  Other devices will be blocked by the firewall, and others could see transfers."
            )
            print("  On your home network, set it to Private:")
            print(
                "  Settings > Network & internet > Ethernet/Wi-Fi > Network profile type > Private"
            )
        print("\n  If your phone can't connect, allow FileSh through the firewall")
        print("  (run once in PowerShell as Administrator):")
        print(
            "  New-NetFirewallRule -DisplayName 'FileSh' -Direction Inbound -Protocol TCP "
            f"-LocalPort {ctx.network_port} -Action Allow -Profile Private"
        )
        print(
            "  New-NetFirewallRule -DisplayName 'FileSh discovery' -Direction Inbound "
            "-Protocol UDP -LocalPort 5353 -Action Allow -Profile Private"
        )
        print("\n  Press Ctrl+C to stop.\n", flush=True)


def _setup_logging(data_dir: Path) -> None:
    if sys.stdout is None or sys.stderr is None:
        # No console (started with pythonw or as the .exe): write to a log file instead.
        data_dir.mkdir(parents=True, exist_ok=True)
        log_file = data_dir / "filesh.log"
        mode = "w" if log_file.exists() and log_file.stat().st_size > MAX_LOG_SIZE else "a"
        stream = open(log_file, mode, encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = stream
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S", stream=sys.stderr
    )


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _running_instance(port: int) -> bool:
    """True if FileSh is already running on this port."""
    request = urllib.request.Request(  # noqa: S310 - fixed local URL
        f"http://127.0.0.1:{port}/api/status", headers={"Host": f"localhost:{port}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
            return "sharing" in json.load(response)
    except (OSError, ValueError):
        return False


def _tray_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import pystray  # noqa: F401
    except Exception:  # noqa: BLE001 - no tray, run in the console instead
        return False
    return True


def main(argv: list[str] | None = None) -> None:
    settings = Settings()
    # First, so messages have somewhere to go when there is no console (the .exe).
    _setup_logging(settings.data_dir)

    parser = argparse.ArgumentParser(prog="FileSh")
    parser.add_argument("--no-tray", action="store_true", help="don't show the tray icon")
    parser.add_argument("--minimized", action="store_true", help="don't open the browser")
    args = parser.parse_args(argv)

    settings.load_saved()
    settings.shared_dir.mkdir(parents=True, exist_ok=True)
    remove_part_files(settings.shared_dir)

    ports = {settings.port} | ({settings.https_port} if settings.https else set())
    busy = sorted(p for p in ports if not _port_free(settings.host, p))
    if busy:
        if _running_instance(settings.port):
            print("FileSh is already running.")
            if not args.minimized:
                webbrowser.open(f"http://localhost:{settings.port}")
            return
        print(f"\nPort {busy[0]} is already used by another program.")
        print("Close it, or start FileSh on another port:")
        print("  $env:FILESH_PORT = '8010'; python -m app.main\n")
        raise SystemExit(1)

    if get_lan_ip() is None:
        logger.warning("No network connection found. Other devices can't connect yet.")

    runner = ServerRunner(settings, open_browser=not args.minimized)
    server_thread = threading.Thread(target=runner.run, name="server", daemon=True)
    server_thread.start()

    icon = None
    if not args.no_tray and _tray_available():
        from app.tray import start_tray

        icon = start_tray(runner)
    try:
        while server_thread.is_alive():
            server_thread.join(0.5)
    except KeyboardInterrupt:
        print("Stopping FileSh...")
        runner.quit()
        server_thread.join(timeout=10)
    finally:
        if icon is not None:
            icon.stop()
