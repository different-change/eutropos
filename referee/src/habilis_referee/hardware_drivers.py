"""Day-1 physical referee drivers for Radwag CBCP-01 balance and overhead camera capture."""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np
import serial

from .beacon import utc_now
from .instruments import ScaleReading, ScaleSample, encode_si_frame, parse_si_frame
from .manifest import canonical_json, sha256_bytes, write_json


class ByteStreamTransport(Protocol):
    """Minimal read/write byte transport matching serial.Serial for physical or loopback tests."""

    def write(self, data: bytes) -> int:
        ...

    def readline(self) -> bytes:
        ...

    def read(self, size: int = 1) -> bytes:
        ...

    def flush(self) -> None:
        ...

    def close(self) -> None:
        ...


class MockCBCP01Transport:
    """In-memory Radwag CBCP-01 wire simulator emitting valid or fault-injected 21-byte frames."""

    def __init__(
        self,
        readings: list[tuple[float, str]] | None = None,
        *,
        tare_g: float = 0.0,
        inject_malformed_at: set[int] | None = None,
        delay_fn: Callable[[int], float] | None = None,
    ) -> None:
        self._readings = list(readings or [(0.0, " ")])
        self._tare_g = float(tare_g)
        self._malformed = set(inject_malformed_at or ())
        self._delay_fn = delay_fn
        self._idx = 0
        self._rx_queue: list[bytes] = []
        self._continuous = False
        self.commands_sent: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        self.commands_sent.append(data)
        if data == b"C1\r\n":
            self._continuous = True
            self._rx_queue.append(b"C1_A\r\n")
        elif data == b"C0\r\n":
            self._continuous = False
            self._rx_queue.append(b"C0_A\r\n")
        elif data == b"SI\r\n":
            self._rx_queue.append(self._next_frame())
        elif data == b"OT\r\n":
            self._rx_queue.append(f"OT {self._tare_g:.2f} g\r\n".encode("ascii"))
        elif data.startswith(b"UT ") and data.endswith(b"\r\n"):
            self._tare_g = float(data[3:-2].strip())
            self._rx_queue.append(b"UT_A\r\n")
        return len(data)

    def _next_frame(self) -> bytes:
        idx = self._idx
        self._idx += 1
        if idx in self._malformed:
            return b"CORRUPT_SI_LINE\r\n"
        mass, stab = self._readings[min(idx, len(self._readings) - 1)]
        return encode_si_frame(mass - self._tare_g, stability=stab)

    def readline(self) -> bytes:
        if self._rx_queue:
            return self._rx_queue.pop(0)
        if self._continuous:
            if self._delay_fn is not None:
                dt = self._delay_fn(self._idx)
                if dt > 0:
                    time.sleep(dt)
            return self._next_frame()
        return b""

    def read(self, size: int = 1) -> bytes:
        return self.readline()[:size]

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class TimestampedScaleFrame:
    index: int
    t_mono_s: float
    wall_utc: str
    raw_hex: str
    reading: ScaleReading


@dataclass
class ScaleCaptureResult:
    boot_id: str
    port: str
    samples: list[ScaleSample]
    frames: list[TimestampedScaleFrame]
    raw_bytes: bytes
    clock_gaps: list[dict[str, Any]] = field(default_factory=list)
    malformed_frames: list[dict[str, Any]] = field(default_factory=list)
    nonmonotonic_clocks: list[dict[str, Any]] = field(default_factory=list)
    timeout_count: int = 0

    @property
    def raw_sha256(self) -> str:
        return sha256_bytes(self.raw_bytes)

    def write_evidence_files(self, scale_path: Path, meta_path: Path) -> None:
        scale_path.parent.mkdir(parents=True, exist_ok=True)
        scale_path.write_bytes(self.raw_bytes)
        write_json(meta_path, {
            "schema": "habilis-cbcp01-capture-v1.0",
            "boot_id": self.boot_id,
            "port": self.port,
            "raw_sha256": self.raw_sha256,
            "frame_count": len(self.frames),
            "clock_gaps": self.clock_gaps,
            "malformed_frames": self.malformed_frames,
            "nonmonotonic_clocks": self.nonmonotonic_clocks,
            "timeout_count": self.timeout_count,
            "samples": [
                {
                    "index": f.index,
                    "t_mono_s": round(f.t_mono_s, 6),
                    "wall_utc": f.wall_utc,
                    "mass_g": f.reading.mass_g,
                    "stability": f.reading.stability,
                }
                for f in self.frames
            ],
        })


class RadwagCBCP01Driver:
    """Driver for Radwag WTC 2000 RS232/USB using CBCP-01 protocol and dual-clock logging."""

    def __init__(
        self,
        port: str = "loop://",
        *,
        baudrate: int = 9600,
        timeout_s: float = 0.5,
        transport: ByteStreamTransport | None = None,
        clock_ns: Callable[[], int] | None = None,
        boot_id: str | None = None,
    ) -> None:
        self.port = port
        self._timeout_s = float(timeout_s)
        self._clock_ns = clock_ns or time.monotonic_ns
        self.boot_id = boot_id or uuid.uuid4().hex[:12]
        if transport is not None:
            self._conn = transport
        else:
            self._conn = serial.serial_for_url(
                port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout_s,
            )

    def _send(self, cmd: bytes) -> bytes:
        self._conn.write(cmd)
        self._conn.flush()
        return self._conn.readline()

    def enable_continuous(self) -> None:
        ack = self._send(b"C1\r\n")
        if ack != b"C1_A\r\n":
            raise ValueError(f"unexpected C1 ack: {ack!r}")

    def disable_continuous(self) -> None:
        ack = self._send(b"C0\r\n")
        if ack != b"C0_A\r\n":
            raise ValueError(f"unexpected C0 ack: {ack!r}")

    def poll_once(self) -> ScaleReading:
        raw = self._send(b"SI\r\n")
        return parse_si_frame(raw)

    def read_tare(self) -> float:
        raw = self._send(b"OT\r\n").decode("ascii", "replace").strip()
        m = re.fullmatch(r"OT\s+([+-]?\d+(?:\.\d+)?)\s+g", raw)
        if not m:
            raise ValueError(f"unparseable tare reply: {raw!r}")
        return float(m.group(1))

    def set_tare(self, tare_g: float) -> None:
        cmd = f"UT {float(tare_g):.2f}\r\n".encode("ascii")
        ack = self._send(cmd)
        if ack != b"UT_A\r\n":
            raise ValueError(f"unexpected UT ack: {ack!r}")

    def capture_stream(
        self,
        *,
        max_frames: int = 30,
        max_gap_s: float = 0.15,
        strict_frames: bool = False,
    ) -> ScaleCaptureResult:
        """Capture sequential CBCP-01 lines with monotonic timestamping and gap auditing."""
        if max_frames < 1:
            raise ValueError("max_frames must be positive")
        t0_ns = self._clock_ns()
        frames: list[TimestampedScaleFrame] = []
        samples: list[ScaleSample] = []
        raw_chunks: list[bytes] = []
        gaps: list[dict[str, Any]] = []
        malformed: list[dict[str, Any]] = []
        nonmonotonic: list[dict[str, Any]] = []
        timeouts = 0
        max_t: float | None = None

        for stream_idx in range(max_frames):
            line = self._conn.readline()
            t_mono_s = (self._clock_ns() - t0_ns) / 1e9
            if not line:
                timeouts += 1
                continue
            try:
                reading = parse_si_frame(line)
            except ValueError as exc:
                if strict_frames:
                    raise
                malformed.append({
                    "stream_index": stream_idx,
                    "t_mono_s": round(t_mono_s, 6),
                    "error": str(exc),
                    "raw_hex": line.hex(),
                })
                continue
            if max_t is not None:
                if t_mono_s <= max_t:
                    nonmonotonic.append({
                        "frame_index": len(frames),
                        "prev_max_t_s": round(max_t, 6),
                        "raw_t_s": round(t_mono_s, 6),
                    })
                else:
                    dt = t_mono_s - max_t
                    if dt > max_gap_s:
                        gaps.append({
                            "frame_index": len(frames),
                            "prev_t_s": round(max_t, 6),
                            "curr_t_s": round(t_mono_s, 6),
                            "gap_s": round(dt, 6),
                        })
            max_t = t_mono_s if max_t is None else max(max_t, t_mono_s)
            idx = len(frames)
            frames.append(TimestampedScaleFrame(idx, t_mono_s, utc_now(), line.hex(), reading))
            samples.append(ScaleSample(t_mono_s, line))
            raw_chunks.append(line)

        return ScaleCaptureResult(
            boot_id=self.boot_id,
            port=self.port,
            samples=samples,
            frames=frames,
            raw_bytes=b"".join(raw_chunks),
            clock_gaps=gaps,
            malformed_frames=malformed,
            nonmonotonic_clocks=nonmonotonic,
            timeout_count=timeouts,
        )

    def close(self) -> None:
        self._conn.close()


@dataclass(frozen=True)
class OverheadFrameCapture:
    index: int
    t_mono_s: float
    wall_utc: str
    exposure_us: int
    gain_db: float
    image_sha256: str
    rgb: np.ndarray


class OverheadCameraDriver:
    """Wrapper for OpenCV UVC, pypylon (when installed), or deterministic synthetic sources."""

    def __init__(
        self,
        *,
        backend: str = "mock",
        device_index: int = 0,
        frame_provider: Callable[[int], np.ndarray] | None = None,
        exposure_us: int = 5000,
        gain_db: float = 0.0,
        clock_ns: Callable[[], int] | None = None,
    ) -> None:
        if backend not in {"mock", "opencv", "pypylon"}:
            raise ValueError(f"unsupported camera backend: {backend!r}")
        self.backend = backend
        self.device_index = device_index
        self.exposure_us = int(exposure_us)
        self.gain_db = float(gain_db)
        self._clock_ns = clock_ns or time.monotonic_ns
        self._provider = frame_provider
        self._cap: Any = None
        if backend == "opencv":
            import cv2

            cap = cv2.VideoCapture(device_index)
            if not cap.isOpened():
                cap.release()
                raise RuntimeError(f"unable to open OpenCV camera device {device_index}")
            self._cap = cap
        elif backend == "pypylon":  # pragma: no cover - requires Basler SDK hardware
            from pypylon import pylon  # type: ignore[import-not-found]

            cam = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
            cam.Open()
            self._cap = cam

    def grab_frame(self, index: int = 0, *, t0_ns: int | None = None) -> OverheadFrameCapture:
        base_ns = self._clock_ns() if t0_ns is None else t0_ns
        if self.backend == "mock":
            if self._provider is not None:
                rgb = np.asarray(self._provider(index), dtype=np.uint8)
            else:
                rgb = np.full((240, 240, 3), 235, dtype=np.uint8)
        elif self.backend == "opencv":
            import cv2

            ok, bgr = self._cap.read()
            if not ok or bgr is None:
                raise RuntimeError("OpenCV camera failed to return frame")
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        else:  # pragma: no cover - requires physical Basler hardware
            res = self._cap.GrabOne(1000)
            rgb = np.asarray(res.Array, dtype=np.uint8)
            res.Release()
        t_mono_s = (self._clock_ns() - base_ns) / 1e9
        digest = hashlib.sha256(rgb.tobytes()).hexdigest()
        return OverheadFrameCapture(
            index=index,
            t_mono_s=max(0.0, t_mono_s),
            wall_utc=utc_now(),
            exposure_us=self.exposure_us,
            gain_db=self.gain_db,
            image_sha256=digest,
            rgb=rgb,
        )

    def close(self) -> None:
        if self._cap is not None:
            if self.backend == "opencv":
                self._cap.release()
            elif self.backend == "pypylon":  # pragma: no cover
                self._cap.Close()
            self._cap = None
