from __future__ import annotations

from dataclasses import dataclass

HEADER = b"\xAA\x55"

TYPE_EVENT = 0x10
TYPE_SLOT_STATUS = 0x20
TYPE_BEEP = 0x21
TYPE_MODE = 0x22
TYPE_SELECTED_SLOT = 0x23
TYPE_LED_MASK = 0x24
TYPE_CLEAR_ALL = 0x25

EVENT_KEY_DOWN = 0x01
EVENT_KEY_UP = 0x02
EVENT_KEY_LONG = 0x03
EVENT_SEND = 0x10


@dataclass(frozen=True)
class Frame:
    frame_type: int
    payload: bytes


def frame_crc(frame_type: int, payload: bytes) -> int:
    value = frame_type ^ len(payload)
    for byte in payload:
        value ^= byte
    return value & 0xFF


def encode_frame(frame_type: int, payload: bytes = b"") -> bytes:
    if not 0 < len(payload) <= 32:
        raise ValueError("payload length must be between 1 and 32 bytes")
    return HEADER + bytes((frame_type, len(payload))) + payload + bytes(
        (frame_crc(frame_type, payload),)
    )


class FrameDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        self._buffer.extend(data)
        frames: list[Frame] = []
        while True:
            start = self._buffer.find(HEADER)
            if start < 0:
                self._buffer[:] = self._buffer[-1:] if self._buffer[-1:] == b"\xAA" else b""
                break
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 5:
                break
            frame_type = self._buffer[2]
            length = self._buffer[3]
            if length == 0 or length > 32:
                del self._buffer[0]
                continue
            total = 5 + length
            if len(self._buffer) < total:
                break
            payload = bytes(self._buffer[4 : 4 + length])
            received_crc = self._buffer[4 + length]
            if received_crc == frame_crc(frame_type, payload):
                frames.append(Frame(frame_type, payload))
                del self._buffer[:total]
            else:
                del self._buffer[0]
        return frames
