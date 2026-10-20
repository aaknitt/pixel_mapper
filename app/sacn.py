"""E1.31 (sACN) output and per-pixel light control.

Unicast to the controller IP is preferred; the yearly notes found multicast to the tree
controller unreliable. Multicast is used when no IP is configured.
"""

from __future__ import annotations

import socket
import struct
import threading
import time
import uuid

E131_PORT = 5568
ACN_ID = b"ASC-E1.17\x00\x00\x00"
VECTOR_ROOT_E131_DATA = 0x00000004
VECTOR_E131_DATA_PACKET = 0x00000002
VECTOR_DMP_SET_PROPERTY = 0x02

# Receivers treat a source as lost after 2.5 s without data.
REFRESH_SECONDS = 1.0
# Keep refreshing this long after the last change, then go quiet so the controller can
# return to its normal show once all pixels are off.
IDLE_RELEASE_SECONDS = 10.0


def multicast_address(universe: int) -> str:
    return f"239.255.{(universe >> 8) & 0xFF}.{universe & 0xFF}"


def build_packet(
    universe: int,
    data: bytes,
    sequence: int,
    cid: bytes,
    source_name: str = "pixel_mapper",
    priority: int = 100,
) -> bytes:
    """Build one E1.31 data packet (ANSI E1.31-2016, start code 0)."""
    if not 1 <= len(data) <= 512:
        raise ValueError("DMX data must be 1-512 bytes")
    if len(cid) != 16:
        raise ValueError("CID must be 16 bytes")
    count = len(data)
    total = 126 + count
    name = source_name.encode("utf-8")[:63].ljust(64, b"\x00")

    root = struct.pack(
        "!HH12sHI16s",
        0x0010,
        0x0000,
        ACN_ID,
        0x7000 | (total - 16),
        VECTOR_ROOT_E131_DATA,
        cid,
    )
    framing = struct.pack(
        "!HI64sBHBBH",
        0x7000 | (total - 38),
        VECTOR_E131_DATA_PACKET,
        name,
        priority,
        0,
        sequence & 0xFF,
        0,
        universe,
    )
    dmp = struct.pack(
        "!HBBHHHB",
        0x7000 | (total - 115),
        VECTOR_DMP_SET_PROPERTY,
        0xA1,
        0x0000,
        0x0001,
        count + 1,
        0x00,
    )
    return root + framing + dmp + bytes(data)


class E131Sender:
    def __init__(self, unicast_ip: str | None = None, source_name: str = "pixel_mapper"):
        self.unicast_ip = unicast_ip or None
        self.source_name = source_name
        self.cid = uuid.uuid4().bytes
        self._seq: dict[int, int] = {}
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 8)

    def send(self, universe: int, data: bytes) -> None:
        seq = (self._seq.get(universe, 0) + 1) & 0xFF
        self._seq[universe] = seq
        packet = build_packet(universe, data, seq, self.cid, self.source_name)
        host = self.unicast_ip or multicast_address(universe)
        self._sock.sendto(packet, (host, E131_PORT))

    def close(self) -> None:
        self._sock.close()


class Lights:
    """Current output for one prop's universes, resent periodically so receivers hold it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sender: E131Sender | None = None
        self._key: tuple | None = None
        self._universes: list[dict] = []
        self._buffers: dict[int, bytearray] = {}
        self._last_change = 0.0
        self._lit = False
        self.state = "off"
        self.last_error: str | None = None
        threading.Thread(target=self._refresh_loop, name="sacn-refresh", daemon=True).start()

    def configure(self, settings: dict) -> None:
        key = (settings["controller_ip"], tuple((u["universe"], u["channels"]) for u in settings["universes"]))
        with self._lock:
            if key == self._key:
                return
            if self._sender:
                self._sender.close()
            self._sender = E131Sender(settings["controller_ip"] or None)
            self._key = key
            self._universes = []
            first = 0
            for u in settings["universes"]:
                count = u["channels"] // 3
                self._universes.append({**u, "first_pixel": first, "pixels": count})
                first += count
            self._buffers = {u["universe"]: bytearray(u["channels"]) for u in self._universes}

    @property
    def total_pixels(self) -> int:
        return sum(u["pixels"] for u in self._universes)

    def all_off(self) -> None:
        self._set({}, None, "off")

    def all_on(self, color: list[int]) -> None:
        self._set(None, color, "all on")

    def show(self, indices: list[int], color: list[int], label: str | None = None) -> None:
        """Light only the given pixel indices (numbered across all universes)."""
        self._set({i: color for i in indices}, None, label or f"pixels {indices}")

    def _set(self, pixels: dict[int, list[int]] | None, fill: list[int] | None, label: str) -> None:
        with self._lock:
            if self._sender is None:
                raise RuntimeError("Lights are not configured for a prop.")
            for u in self._universes:
                buf = self._buffers[u["universe"]]
                if fill is not None:
                    rgb = bytes(fill)
                    buf[: u["pixels"] * 3] = rgb * u["pixels"]
                else:
                    buf[:] = bytes(len(buf))
                    for i, color in (pixels or {}).items():
                        local = i - u["first_pixel"]
                        if 0 <= local < u["pixels"]:
                            buf[local * 3 : local * 3 + 3] = bytes(color)
            self._lit = fill is not None or bool(pixels)
            self._last_change = time.time()
            self.state = label
            self._flush_locked()

    def _flush_locked(self) -> None:
        try:
            for u in self._universes:
                self._sender.send(u["universe"], bytes(self._buffers[u["universe"]]))
            self.last_error = None
        except OSError as exc:
            self.last_error = str(exc)

    def _refresh_loop(self) -> None:
        while True:
            time.sleep(REFRESH_SECONDS)
            with self._lock:
                if self._sender is None:
                    continue
                if self._lit or time.time() - self._last_change < IDLE_RELEASE_SECONDS:
                    self._flush_locked()
