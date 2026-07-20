from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from .protocol import Frame, FrameDecoder, encode_frame

LOGGER = logging.getLogger(__name__)


class MemoryTransport:
    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def send(self, frame_type: int, payload: bytes) -> None:
        self.frames.append(encode_frame(frame_type, payload))


class SerialTransport:
    def __init__(
        self,
        port: str,
        baud: int,
        on_frame: Callable[[Frame], None],
        on_connect: Callable[[], None] | None = None,
    ) -> None:
        self.port = port
        self.baud = baud
        self.on_frame = on_frame
        self.on_connect = on_connect
        self._serial = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="fpga-serial", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        with self._lock:
            if self._serial is not None:
                self._serial.close()
                self._serial = None

    def send(self, frame_type: int, payload: bytes) -> None:
        data = encode_frame(frame_type, payload)
        with self._lock:
            if self._serial is not None and self._serial.is_open:
                self._serial.write(data)

    def _run(self) -> None:
        try:
            import serial
        except ImportError:
            LOGGER.error("pyserial is not installed; serial transport is disabled")
            return
        decoder = FrameDecoder()
        while not self._stop.is_set():
            try:
                connected = False
                with self._lock:
                    if self._serial is None or not self._serial.is_open:
                        self._serial = serial.Serial(self.port, self.baud, timeout=0.1)
                        LOGGER.info("connected to FPGA on %s", self.port)
                        connected = True
                    device = self._serial
                if connected and self.on_connect:
                    self.on_connect()
                # Some Windows CH340 drivers reject overlapped read/write
                # operations on the same handle. Keep the short read under
                # the same lock as send() so the heartbeat cannot interrupt
                # an incoming FPGA frame.
                with self._lock:
                    data = device.read(64)
                for frame in decoder.feed(data):
                    self.on_frame(frame)
            except Exception as exc:
                LOGGER.warning("serial connection unavailable: %s", exc)
                decoder = FrameDecoder()
                with self._lock:
                    if self._serial is not None:
                        try:
                            self._serial.close()
                        finally:
                            self._serial = None
                self._stop.wait(2.0)
