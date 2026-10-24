"""
mdns.py — mDNS / DNS-SD discovery for LAN mode (stdlib only).

Why stdlib: ``zeroconf`` is not installed in Sangam's venv, and adding a
dependency for one feature is out of scope for this batch. This module
therefore implements the smallest honest subset of mDNS itself:

- Advertisement: a Sangam instance announces
  ``<instance>._sangam._tcp.local.`` (PTR + SRV + TXT + A records) on the
  link-local multicast group 224.0.0.251:5353 with TTL=1, so packets
  never leave the LAN segment.
- Discovery: a listener thread parses PTR/SRV/TXT/A records from other
  hosts and exposes currently visible peers with a last-seen timestamp;
  peers expire after ``PEER_TTL_S``.

Honest scope, stated plainly:
- This is advertisement + peer observation, NOT a full mDNS responder:
  it does not answer queries for other services, does not do conflict
  resolution for duplicate instance names, and does not implement
  DNS-SD browsing of arbitrary service types.
- If UDP port 5353 cannot be bound (already in use, restricted), the
  module degrades to advertisement-only: announcements are still sent
  (from an ephemeral source port) but no peers can be observed, and
  :func:`mdns_status` says so explicitly instead of pretending discovery
  works. QR re-scan remains the fallback discovery path.
- Everything is OFF unless the caller passes ``enabled=True`` (the
  devices route passes the LAN_ENABLED settings flag). Nothing here
  binds, sends, or listens on its own at import time.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field

MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353
SERVICE_TYPE = "_sangam._tcp.local."
PEER_TTL_S = 120.0
ANNOUNCE_INTERVAL_S = 20.0

_TYPE_PTR = 12
_TYPE_TXT = 16
_TYPE_A = 1
_TYPE_SRV = 33
_CLASS_IN = 1


def instance_name(hostname: str | None = None) -> str:
    """DNS-SD instance name: 'Sangam-<hostname>' with unsafe chars stripped."""
    host = (hostname or socket.gethostname() or "host").strip()
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in host) or "host"
    return f"Sangam-{safe}"


def local_advertisement(port: int, ips: list[str] | None = None,
                        hostname: str | None = None) -> dict:
    """The advertisement this instance would publish (pure function, no I/O)."""
    return {
        "service_type": SERVICE_TYPE,
        "instance": instance_name(hostname),
        "port": int(port),
        "ips": list(ips or []),
        "txt": {"version": "1", "path": "/"},
    }


# ---------------------------------------------------------------------------
# Minimal DNS packet building / parsing (enough for our own records)
# ---------------------------------------------------------------------------

def _encode_name(name: str) -> bytes:
    out = b""
    for label in name.rstrip(".").split("."):
        raw = label.encode("utf-8")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def _decode_name(data: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    end = offset
    while True:
        if offset >= len(data):
            break
        length = data[offset]
        if length == 0:
            offset += 1
            if not jumped:
                end = offset
            break
        if length & 0xC0 == 0xC0:  # compression pointer
            pointer = ((length & 0x3F) << 8) | data[offset + 1]
            if not jumped:
                end = offset + 2
            jumped = True
            offset = pointer
            continue
        offset += 1
        labels.append(data[offset:offset + length].decode("utf-8", errors="replace"))
        offset += length
    return ".".join(labels), end


def _record(name: str, rtype: int, ttl: int, rdata: bytes) -> bytes:
    return (_encode_name(name) + struct.pack(">HHIH", rtype, _CLASS_IN, ttl, len(rdata))
            + rdata)


def build_announcement(instance: str, port: int, ips: list[str],
                       txt: dict[str, str] | None = None) -> bytes:
    """One mDNS response packet: PTR + SRV + TXT + A records."""
    service_instance = f"{instance}.{SERVICE_TYPE}"
    txt = txt or {"version": "1", "path": "/"}
    txt_data = b"".join(
        bytes([len(f"{k}={v}".encode())]) + f"{k}={v}".encode()
        for k, v in sorted(txt.items()))
    target = f"{instance}.local."
    answers = [
        _record(SERVICE_TYPE, _TYPE_PTR, 120, _encode_name(service_instance)),
        _record(service_instance, _TYPE_SRV, 120,
                struct.pack(">HHH", 0, 0, port) + _encode_name(target)),
        _record(service_instance, _TYPE_TXT, 120, txt_data),
    ]
    for ip in ips:
        try:
            answers.append(_record(target, _TYPE_A, 120, socket.inet_aton(ip)))
        except OSError:
            continue
    header = struct.pack(">HHHHHH", 0, 0x8400, 0, len(answers), 0, 0)
    return header + b"".join(answers)


def parse_mdns_packet(data: bytes) -> list[dict]:
    """Parse an mDNS packet's answer records into peer observations.

    Returns a list of peer dicts ``{instance, port, ips, txt, last_seen}``
    merged per service instance found in the packet. Malformed packets
    yield [] instead of raising — mDNS traffic is untrusted input.
    """
    peers: dict[str, dict] = {}
    try:
        if len(data) < 12:
            return []
        _id, _flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", data[:12])
        offset = 12
        for _ in range(qd):  # skip questions
            _name, offset = _decode_name(data, offset)
            offset += 4
        for _ in range(an):
            name, offset = _decode_name(data, offset)
            if offset + 10 > len(data):
                break
            rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[offset:offset + 10])
            offset += 10
            rdata = data[offset:offset + rdlen]
            offset += rdlen
            if rtype == _TYPE_PTR:
                target, _ = _decode_name(rdata, 0)
                inst = target.removesuffix("." + SERVICE_TYPE).removesuffix("." + SERVICE_TYPE.rstrip("."))
                peers.setdefault(inst, {"instance": inst, "port": None, "ips": [], "txt": {}})
            elif rtype == _TYPE_SRV:
                if len(rdata) >= 6:
                    port = struct.unpack(">H", rdata[4:6])[0]
                    inst = name.removesuffix("." + SERVICE_TYPE).removesuffix("." + SERVICE_TYPE.rstrip("."))
                    peer = peers.setdefault(inst, {"instance": inst, "port": None, "ips": [], "txt": {}})
                    peer["port"] = port
            elif rtype == _TYPE_TXT:
                inst = name.removesuffix("." + SERVICE_TYPE).removesuffix("." + SERVICE_TYPE.rstrip("."))
                peer = peers.setdefault(inst, {"instance": inst, "port": None, "ips": [], "txt": {}})
                i = 0
                while i < len(rdata):
                    ln = rdata[i]
                    i += 1
                    chunk = rdata[i:i + ln].decode("utf-8", errors="replace")
                    i += ln
                    if "=" in chunk:
                        key, value = chunk.split("=", 1)
                        peer["txt"][key] = value
            elif rtype == _TYPE_A:
                # A records are keyed by target host, not instance; attach
                # to every peer whose instance matches the host prefix.
                host = name.removesuffix(".local").removesuffix(".local.")
                try:
                    ip = socket.inet_ntoa(rdata[:4])
                except OSError:
                    continue
                for peer in peers.values():
                    if peer["instance"] == host and ip not in peer["ips"]:
                        peer["ips"].append(ip)
    except (struct.error, IndexError, ValueError):
        return []
    now = time.time()
    for peer in peers.values():
        peer["last_seen"] = now
    return list(peers.values())


@dataclass
class _Peer:
    instance: str
    port: int | None = None
    ips: list[str] = field(default_factory=list)
    txt: dict = field(default_factory=dict)
    last_seen: float = 0.0


class MdnsAdvertiser:
    """Advertise this instance and (when possible) observe peers.

    Thread-safe; start/stop are idempotent. Never starts unless
    ``enabled`` is True — callers wire this to LAN_ENABLED.
    """

    def __init__(self, port: int, ips: list[str] | None = None,
                 hostname: str | None = None):
        self.port = int(port)
        self.ips = list(ips or [])
        self.instance = instance_name(hostname)
        self._peers: dict[str, _Peer] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listener: threading.Thread | None = None
        self.running = False
        self.listener_ok = False
        self.note = ""

    # -- lifecycle ------------------------------------------------------
    def start(self, enabled: bool) -> bool:
        """Start advertising iff enabled. Returns True iff advertising."""
        if not enabled:
            self.note = "mDNS off: LAN mode is not enabled"
            return False
        if self.running:
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._announce_loop, daemon=True)
        self._thread.start()
        self._listener = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener.start()
        self.running = True
        self.note = ("advertising + listening" if self.listener_ok else
                     "advertising only (port 5353 unavailable for listening; "
                     "QR re-scan remains the discovery fallback)")
        return True

    def stop(self) -> None:
        self._stop.set()
        self.running = False
        self.listener_ok = False

    # -- loops ----------------------------------------------------------
    def _announce_loop(self) -> None:
        packet = build_announcement(self.instance, self.port, self.ips)
        self._send(packet)  # announce immediately, then every interval
        while not self._stop.wait(ANNOUNCE_INTERVAL_S):
            self._send(packet)
        # One final goodbye is not sent: peers expire via PEER_TTL_S.

    def _send(self, packet: bytes) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)  # LAN only
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
                sock.sendto(packet, (MDNS_GROUP, MDNS_PORT))
        except OSError:
            pass  # best-effort: a failed announcement is not an app error

    def _listen_loop(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", MDNS_PORT))
            mreq = struct.pack("4sL", socket.inet_aton(MDNS_GROUP), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(1.0)
        except OSError:
            self.listener_ok = False
            self.note = ("advertising only (port 5353 unavailable for listening; "
                         "QR re-scan remains the discovery fallback)")
            return
        self.listener_ok = True
        self.note = "advertising + listening"
        try:
            while not self._stop.is_set():
                try:
                    data, _addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break
                for obs in parse_mdns_packet(data):
                    if obs["instance"] == self.instance:
                        continue  # ignore our own announcements
                    with self._lock:
                        peer = self._peers.get(obs["instance"])
                        if peer is None:
                            peer = _Peer(instance=obs["instance"])
                            self._peers[obs["instance"]] = peer
                        peer.port = obs["port"] or peer.port
                        peer.txt = obs["txt"] or peer.txt
                        for ip in obs["ips"]:
                            if ip not in peer.ips:
                                peer.ips.append(ip)
                        peer.last_seen = obs["last_seen"]
        finally:
            sock.close()

    # -- observation ------------------------------------------------------
    def visible_peers(self) -> list[dict]:
        """Peers seen within PEER_TTL_S (own instance excluded)."""
        now = time.time()
        with self._lock:
            peers = [p for p in self._peers.values() if now - p.last_seen <= PEER_TTL_S]
        return [{
            "instance": p.instance,
            "service_type": SERVICE_TYPE,
            "port": p.port,
            "ips": list(p.ips),
            "txt": dict(p.txt),
            "last_seen": p.last_seen,
        } for p in peers]

    def status(self) -> dict:
        return {
            "running": self.running,
            "service_type": SERVICE_TYPE,
            "advertisement": local_advertisement(self.port, self.ips) if self.running else None,
            "peers": self.visible_peers(),
            "listener_ok": self.listener_ok,
            "note": self.note or "mDNS not started",
        }


# -- process-wide singleton (the devices route uses this) -------------------

_ADVERTISER: MdnsAdvertiser | None = None
_ADVERTISER_LOCK = threading.Lock()


def start_mdns(port: int, enabled: bool, ips: list[str] | None = None) -> MdnsAdvertiser | None:
    """Start (or reuse) the singleton advertiser. Returns None when disabled."""
    global _ADVERTISER
    with _ADVERTISER_LOCK:
        if not enabled:
            if _ADVERTISER is not None:
                _ADVERTISER.stop()
            return None
        if _ADVERTISER is None or _ADVERTISER.port != int(port):
            if _ADVERTISER is not None:
                _ADVERTISER.stop()
            _ADVERTISER = MdnsAdvertiser(int(port), ips=ips)
        _ADVERTISER.start(enabled=True)
        return _ADVERTISER


def stop_mdns() -> None:
    global _ADVERTISER
    with _ADVERTISER_LOCK:
        if _ADVERTISER is not None:
            _ADVERTISER.stop()
            _ADVERTISER = None


def mdns_status() -> dict:
    if _ADVERTISER is None:
        return {
            "running": False,
            "service_type": SERVICE_TYPE,
            "advertisement": None,
            "peers": [],
            "listener_ok": False,
            "note": "mDNS off: LAN mode is not enabled (or discovery was never started)",
        }
    return _ADVERTISER.status()
