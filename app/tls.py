"""Self-signed HTTPS certificate for the local network (SECURITY.md 2.9)."""

import datetime
import ipaddress
import logging
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

logger = logging.getLogger("filesh")

VALID_DAYS = 397
RENEW_BEFORE_DAYS = 30


def _names_in(cert: x509.Certificate) -> set[str]:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return set()
    names = set(san.get_values_for_type(x509.DNSName))
    names |= {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    return names


def ensure_certificate(folder: Path, hostnames: list[str], ips: list[str]) -> tuple[Path, Path]:
    """Return (certificate, key) files, making a new pair if the names changed or it expires."""
    cert_file, key_file = folder / "cert.pem", folder / "key.pem"
    wanted = set(hostnames) | set(ips)
    now = datetime.datetime.now(datetime.UTC)

    if cert_file.exists() and key_file.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
            expires_soon = cert.not_valid_after_utc - now < datetime.timedelta(RENEW_BEFORE_DAYS)
            if wanted <= _names_in(cert) and not expires_soon:
                return cert_file, key_file
        except ValueError:
            pass

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FileSh")])
    alt_names: list[x509.GeneralName] = [x509.DNSName(h) for h in sorted(set(hostnames))]
    alt_names += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in sorted(set(ips))]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    folder.mkdir(parents=True, exist_ok=True)
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    _write(key_file, key_bytes)
    _write(cert_file, cert.public_bytes(serialization.Encoding.PEM))
    logger.info("Created a new HTTPS certificate")
    return cert_file, key_file


def fingerprint(cert_file: Path) -> str:
    """SHA-256 fingerprint, so the user can compare it with what the phone's browser shows."""
    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    digest = cert.fingerprint(hashes.SHA256()).hex().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def _write(path: Path, data: bytes) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)
