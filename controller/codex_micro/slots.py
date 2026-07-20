from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
from threading import RLock


class SlotStatus(IntEnum):
    EMPTY = 0
    IDLE = 1
    RUNNING = 2
    APPROVAL = 3
    COMPLETED = 4
    ERROR = 5
    UNKNOWN = 6


@dataclass
class SessionIdentity:
    session_id: str
    deeplink: str
    title: str = ""


@dataclass
class Slot:
    index: int
    status: SlotStatus = SlotStatus.EMPTY
    session_id: str = ""
    deeplink: str = ""
    title: str = ""

    @property
    def bound(self) -> bool:
        return bool(self.session_id)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["status"] = int(self.status)
        data["bound"] = self.bound
        return data


class SlotRegistry:
    def __init__(self) -> None:
        self._slots = [Slot(index=index) for index in range(4)]
        self._lock = RLock()

    def get(self, index: int) -> Slot:
        self._validate(index)
        return self._slots[index]

    def all(self) -> list[Slot]:
        return self._slots.copy()

    def bind(self, index: int, identity: SessionIdentity) -> Slot:
        self._validate(index)
        if not identity.session_id.strip():
            raise ValueError("session_id cannot be empty")
        with self._lock:
            existing = self.find(identity.session_id)
            if existing is not None and existing.index != index:
                self.clear(existing.index)
            slot = self._slots[index]
            slot.session_id = identity.session_id.strip()
            slot.deeplink = identity.deeplink.strip()
            slot.title = identity.title.strip()
            slot.status = SlotStatus.IDLE
            return slot

    def clear(self, index: int) -> Slot:
        self._validate(index)
        with self._lock:
            self._slots[index] = Slot(index=index)
            return self._slots[index]

    def clear_all(self) -> None:
        with self._lock:
            self._slots = [Slot(index=index) for index in range(4)]

    def find(self, session_id: str) -> Slot | None:
        return next((slot for slot in self._slots if slot.session_id == session_id), None)

    def first_empty(self) -> Slot | None:
        return next((slot for slot in self._slots if not slot.bound), None)

    def set_status(self, index: int, status: SlotStatus) -> tuple[Slot, bool]:
        self._validate(index)
        with self._lock:
            slot = self._slots[index]
            if status != SlotStatus.EMPTY and not slot.bound:
                raise ValueError("cannot set a non-empty status on an unbound slot")
            completed_transition = (
                status == SlotStatus.COMPLETED and slot.status != SlotStatus.COMPLETED
            )
            slot.status = status
            return slot, completed_transition

    @staticmethod
    def _validate(index: int) -> None:
        if index not in range(4):
            raise IndexError("slot index must be between 0 and 3")
