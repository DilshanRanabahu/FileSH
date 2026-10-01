"""Automatic discovery with mDNS: the PC answers to "filesh.local" on the local network.

Only the name, address, and port are announced; never the token or PIN (SECURITY.md 2.14).
"""

import logging
import socket

from zeroconf import IPVersion, ServiceInfo, Zeroconf

logger = logging.getLogger("filesh")

HOSTNAME = "filesh.local"
SERVICE_TYPE = "_http._tcp.local."


class Discovery:
    def __init__(self) -> None:
        self._zeroconf: Zeroconf | None = None
        self._info: ServiceInfo | None = None
        self.hostname: str | None = None

    def start(self, ip: str, port: int, https: bool) -> None:
        """Blocking (takes a few seconds); run it in a thread."""
        self.stop()
        pc_name = socket.gethostname()
        info = ServiceInfo(
            SERVICE_TYPE,
            f"FileSh on {pc_name}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip)],
            port=port,
            properties={"path": "/", "scheme": "https" if https else "http"},
            server=f"{HOSTNAME}.",
        )
        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        try:
            zeroconf.register_service(info, allow_name_change=True)
        except Exception as exc:  # noqa: BLE001 - discovery is optional
            zeroconf.close()
            logger.warning("Automatic discovery is not available: %s", type(exc).__name__)
            return
        self._zeroconf, self._info, self.hostname = zeroconf, info, HOSTNAME
        logger.info("Discoverable as %s", HOSTNAME)

    def stop(self) -> None:
        if self._zeroconf is None:
            return
        try:
            if self._info is not None:
                self._zeroconf.unregister_service(self._info)
        finally:
            self._zeroconf.close()
            self._zeroconf, self._info, self.hostname = None, None, None
