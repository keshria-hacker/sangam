"""lan_pairing.py — Batch 6: LAN device pairing + paired-device tokens.

Single-user LAN access: the laptop hosts Sangam; a phone on the same
Wi-Fi pairs by scanning a QR code (or typing a 6-digit code) and getting
host approval. Pairing issues a per-device Bearer token that is stored
server-side ONLY as a SHA-256 hash — the raw token is returned exactly
once, at claim time, and never again.

Deliberately NOT reusing auth._create_session: that helper deletes all
previous sessions for the user, which would log the laptop out when the
phone pairs. Device tokens live in their own table and never touch the
session table.

Pending pairings (code + approval state, 5-minute lifetime) are kept in
memory, not in the database: they are ephemeral by design, and a server
restart simply means the host starts a fresh pairing. Paired devices are
durable rows (see PairedDevice).

TLS: the host can generate a self-signed certificate (``cryptography``
if installed, else the ``openssl`` CLI) into ``mainfiles/config/lan-cert/``
(gitignored). Generating the cert does NOT switch the running server to
TLS — the operator restarts uvicorn with ``--ssl-certfile/--ssl-keyfile``
pointing at those files. The fingerprint is shown next to the QR code so
the phone owner can compare it manually: browsers do not allow a web
page to pin a certificate automatically, so fingerprint comparison on
first connect is the honest mechanism (see the Devices UI text).
"""
from __future__ import annotations

import hashlib
import secrets
import socket
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .config import BASE_DIR
from .database import Base

PAIRING_CODE_TTL = timedelta(minutes=5)
DEVICE_TOKEN_TTL = timedelta(days=90)
PAIRING_START_LIMIT = 10          # starts per host per window
PAIRING_START_WINDOW_S = 900      # 15 minutes
CLAIM_FAIL_LIMIT = 5              # wrong codes per client IP per window
CLAIM_FAIL_WINDOW_S = 900         # 15 minutes

CERT_DIR = BASE_DIR / "config" / "lan-cert"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"


def _now() -> datetime:
    return datetime.now(UTC)


def as_aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; comparisons against aware
    ``datetime.now(UTC)`` raise TypeError. Normalize on read."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _hash_token(token: str) -> str:
    """SHA-256 hex of a token. Same scheme as auth sessions; duplicated
    here (not imported from auth) so auth.py can import this module
    without a circular import."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class PairedDevice(Base):
    """A phone (or other device) paired over LAN. One row per device;
    ``token_hash`` is all the server ever stores — the raw token is
    returned to the device exactly once at claim time."""

    __tablename__ = "paired_devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    device_name: Mapped[str] = mapped_column(String(200), default="Paired device")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


# ---------------------------------------------------------------------------
# Pending pairings (in-memory, ephemeral)
# ---------------------------------------------------------------------------

class Pairing:
    """One in-flight pairing: code shown on the host, approval clicked on
    the host, claimed once by the phone."""

    def __init__(self, user_id: str, device_name: str):
        self.pairing_id = _new_id("pair")
        # 6-digit code, unique among live pairings (checked by caller).
        self.code = f"{secrets.randbelow(900000) + 100000:06d}"
        self.device_name = device_name or "Phone"
        self.user_id = user_id
        self.status = "pending"  # pending | approved | denied | expired | claimed
        self.created_at = _now()
        self.expires_at = self.created_at + PAIRING_CODE_TTL

    def sweep(self) -> None:
        if self.status in ("pending", "approved") and _now() >= self.expires_at:
            self.status = "expired"

    def public(self) -> dict:
        self.sweep()
        return {
            "pairing_id": self.pairing_id,
            "device_name": self.device_name,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


# pairing_id -> Pairing. Single-process server; see module docstring.
PAIRINGS: dict[str, Pairing] = {}


def create_pairing(user_id: str, device_name: str) -> Pairing:
    for p in list(PAIRINGS.values()):
        p.sweep()
    pairing = Pairing(user_id, device_name)
    live_codes = {p.code for p in PAIRINGS.values() if p.status in ("pending", "approved")}
    while pairing.code in live_codes:
        pairing.code = f"{secrets.randbelow(900000) + 100000:06d}"
    PAIRINGS[pairing.pairing_id] = pairing
    return pairing


def find_pairing_by_code(code: str) -> Pairing | None:
    for p in PAIRINGS.values():
        p.sweep()
        if p.code == code and p.status in ("pending", "approved", "denied", "expired", "claimed"):
            return p
    return None


def expire_all_pairings() -> int:
    """Expire every pending/approved pairing (used on cert regeneration)."""
    n = 0
    for p in PAIRINGS.values():
        p.sweep()
        if p.status in ("pending", "approved"):
            p.status = "expired"
            n += 1
    return n


# ---------------------------------------------------------------------------
# LAN addresses (stdlib only, no new dependencies)
# ---------------------------------------------------------------------------

def lan_ipv4_addresses() -> list[str]:
    """Non-loopback IPv4 addresses of this host (the addresses a phone on
    the same Wi-Fi would use). Best-effort: returns [] when detection
    fails instead of raising."""
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    # Fallback: the address the host would use for outbound traffic.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


# ---------------------------------------------------------------------------
# Self-signed certificate (cryptography preferred, openssl CLI fallback)
# ---------------------------------------------------------------------------

def cert_fingerprint() -> str | None:
    """SHA-256 hex of the DER certificate, or None when no cert exists."""
    if not CERT_FILE.exists():
        return None
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding

        cert = x509.load_pem_x509_certificate(CERT_FILE.read_bytes())
        return hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()
    except Exception:
        return None


def cert_info() -> dict:
    fp = cert_fingerprint()
    created = None
    if CERT_FILE.exists():
        try:
            created = datetime.fromtimestamp(CERT_FILE.stat().st_mtime, tz=UTC).isoformat()
        except Exception:
            created = None
    return {"exists": fp is not None, "fingerprint_sha256": fp, "created_at": created}


def generate_cert(common_name: str = "sangam-lan") -> dict:
    """Create (or replace) a self-signed certificate for the host's LAN
    addresses + localhost. Returns cert_info(). Raises RuntimeError when
    neither cryptography nor the openssl CLI is available.

    The key and cert are written to config/lan-cert/ (gitignored) with
    owner-only permissions on the key. This does NOT reload the running
    server: restart uvicorn with --ssl-certfile/--ssl-keyfile to serve
    TLS.
    """
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    san_ips = lan_ipv4_addresses() or ["127.0.0.1"]
    try:
        import ipaddress

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now())
            .not_valid_after(_now() + timedelta(days=365))
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address(ip)) for ip in san_ips]
                    + [x509.DNSName("localhost")]
                ),
                critical=False,
            )
        )
        cert = builder.sign(key, hashes.SHA256())
        KEY_FILE.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
        CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    except ImportError:
        _generate_cert_openssl(san_ips, common_name)
    try:
        KEY_FILE.chmod(0o600)
    except Exception:
        pass
    return cert_info()


def _generate_cert_openssl(san_ips: list[str], common_name: str) -> None:
    """openssl CLI fallback (30s timeout). Raises RuntimeError on failure."""
    import subprocess

    san = ",".join(f"IP:{ip}" for ip in san_ips) + ",DNS:localhost"
    cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(KEY_FILE), "-out", str(CERT_FILE),
        "-days", "365", "-nodes",
        "-subj", f"/CN={common_name}",
        "-addext", f"subjectAltName={san}",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise RuntimeError("Neither the 'cryptography' package nor the 'openssl' CLI is available — cannot generate a certificate.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("openssl certificate generation timed out.")
    if proc.returncode != 0 or not CERT_FILE.exists():
        raise RuntimeError(f"openssl certificate generation failed: {(proc.stderr or '').strip()[:300]}")
