from __future__ import annotations

import ctypes
import logging
import os
import re
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from .slots import SessionIdentity, Slot

LOGGER = logging.getLogger(__name__)

VK_CONTROL = 0x11
VK_MENU = 0x12
VK_RMENU = 0xA5
VK_BACK = 0x08
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_RETURN = 0x0D

KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class INPUTUNION(ctypes.Union):
    _fields_ = (
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    )


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = (
        ("type", wintypes.DWORD),
        ("union", INPUTUNION),
    )


class DesktopError(RuntimeError):
    pass


class KeyboardInjector:
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def key_down(self, virtual_key: int) -> None:
        if self.dry_run:
            LOGGER.info("key down: 0x%02x", virtual_key)
            return
        self._send(virtual_key, 0)

    def key_up(self, virtual_key: int) -> None:
        if self.dry_run:
            LOGGER.info("key up: 0x%02x", virtual_key)
            return
        self._send(virtual_key, KEYEVENTF_KEYUP)

    def press(self, virtual_key: int) -> None:
        self.key_down(virtual_key)
        self.key_up(virtual_key)

    def combo(self, *virtual_keys: int) -> None:
        for key in virtual_keys:
            self.key_down(key)
        for key in reversed(virtual_keys):
            self.key_up(key)

    @staticmethod
    def _send(virtual_key: int, flags: int) -> None:
        input_data = INPUT(
            type=INPUT_KEYBOARD,
            ki=KEYBDINPUT(
                wVk=virtual_key,
                wScan=0,
                dwFlags=flags,
                time=0,
                dwExtraInfo=0,
            ),
        )
        user32 = ctypes.windll.user32
        user32.SendInput.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        )
        user32.SendInput.restype = wintypes.UINT
        if user32.SendInput(1, ctypes.byref(input_data), ctypes.sizeof(INPUT)) != 1:
            raise ctypes.WinError()


@dataclass
class ClipboardSnapshot:
    text: str


class Clipboard:
    def __init__(self) -> None:
        try:
            import pyperclip
        except ImportError as exc:
            raise DesktopError("pyperclip is required for desktop binding") from exc
        self._pyperclip = pyperclip

    def read(self) -> str:
        return str(self._pyperclip.paste() or "")

    def write(self, value: str) -> None:
        self._pyperclip.copy(value)

    def snapshot(self) -> ClipboardSnapshot:
        return ClipboardSnapshot(self.read())

    def restore(self, snapshot: ClipboardSnapshot) -> None:
        self.write(snapshot.text)


class ChatWindow:
    TITLES = ("chatgpt", "codex")

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def _is_chat_window(self, hwnd: int) -> bool:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if not length:
            return False
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return any(value in buffer.value.lower() for value in self.TITLES)

    def find_handle(self) -> int | None:
        if self.dry_run:
            return 1
        handles: list[int] = []

        foreground = ctypes.windll.user32.GetForegroundWindow()
        if foreground and self._is_chat_window(foreground):
            return foreground

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd: int, _lparam: int) -> bool:
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            if self._is_chat_window(hwnd):
                handles.append(hwnd)
                return False
            return True

        ctypes.windll.user32.EnumWindows(callback, 0)
        return handles[0] if handles else None

    def process_id(self) -> int | None:
        hwnd = self.find_handle()
        if not hwnd or self.dry_run:
            return None if not hwnd else 1
        process_id = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return int(process_id.value) or None

    def focus(self) -> bool:
        hwnd = self.find_handle()
        if not hwnd:
            return False
        if self.dry_run or ctypes.windll.user32.GetForegroundWindow() == hwnd:
            return True
        ctypes.windll.user32.ShowWindow(hwnd, 5)
        return bool(ctypes.windll.user32.SetForegroundWindow(hwnd))

    def minimize(self) -> bool:
        hwnd = self.find_handle()
        if not hwnd:
            return False
        if not self.dry_run:
            ctypes.windll.user32.ShowWindow(hwnd, 6)
        return True

    def current_title(self) -> str:
        if self.dry_run:
            return "Dry session"
        hwnd = self.find_handle()
        if not hwnd:
            return ""
        try:
            from pywinauto import Desktop

            window = Desktop(backend="uia").window(handle=hwnd)
            window_rect = window.rectangle()
            candidates = []
            for element in window.descendants(control_type="Text"):
                name = str(element.element_info.name or "").strip()
                rect = element.rectangle()
                if (
                    name
                    and rect.top >= 35
                    and rect.top <= 140
                    and rect.left > window_rect.left + 500
                    and not re.fullmatch(r"\d{1,2}:\d{2}", name)
                    and not name.casefold().startswith(("working ", "running "))
                    and name.casefold() not in {"chatgpt", "codex"}
                ):
                    candidates.append((rect.top, rect.left, name))
            if candidates:
                return sorted(candidates)[0][2]
        except Exception:
            LOGGER.debug("could not read current ChatGPT title", exc_info=True)
        return ""


class DesktopAdapter:
    def __init__(
        self,
        dry_run: bool = False,
        settle_seconds: float = 0.35,
        send_hotkey: tuple[int, ...] = (VK_RETURN,),
    ) -> None:
        self.dry_run = dry_run
        self.settle_seconds = settle_seconds
        self.send_hotkey = send_hotkey
        self.keyboard = KeyboardInjector(dry_run=dry_run)
        self.window = ChatWindow(dry_run=dry_run)
        self.clipboard = None if dry_run else Clipboard()
        self._dry_counter = 0
        self._repeat_lock = threading.Lock()
        self._repeat_controls: dict[int, tuple[threading.Event, threading.Thread]] = {}

    def process_token(self) -> int | None:
        return self.window.process_id()

    def capture_current(self) -> SessionIdentity:
        if self.dry_run:
            self._dry_counter += 1
            return SessionIdentity(
                session_id=f"dry-session-{self._dry_counter}",
                deeplink=f"codex://dry-session-{self._dry_counter}",
                title=f"Dry session {self._dry_counter}",
            )
        if not self.window.focus():
            raise DesktopError("ChatGPT/Codex desktop window was not found")
        assert self.clipboard is not None
        snapshot = self.clipboard.snapshot()
        try:
            self.keyboard.combo(VK_CONTROL, VK_MENU, ord("C"))
            time.sleep(self.settle_seconds)
            session_id = self.clipboard.read().strip()
            self.keyboard.combo(VK_CONTROL, VK_MENU, ord("L"))
            time.sleep(self.settle_seconds)
            deeplink = self.clipboard.read().strip()
        finally:
            self.clipboard.restore(snapshot)
        if not session_id:
            raise DesktopError("Copy session ID shortcut returned an empty value")
        if not deeplink:
            raise DesktopError("Copy deeplink shortcut returned an empty value")
        return SessionIdentity(
            session_id=session_id,
            deeplink=deeplink,
            title=self.window.current_title(),
        )

    def activate(self, slot: Slot) -> None:
        if not slot.bound:
            raise DesktopError(f"slot {slot.index} is not bound")
        if self.dry_run:
            LOGGER.info("activate slot %d: %s", slot.index, slot.session_id)
            return
        activated = False
        if slot.deeplink:
            try:
                os.startfile(slot.deeplink)  # type: ignore[attr-defined]
                activated = True
                time.sleep(max(self.settle_seconds, 0.7))
            except OSError:
                LOGGER.warning("deeplink failed, falling back to Ctrl+%d", slot.index + 1)
        if not activated:
            if not self.window.focus():
                raise DesktopError("ChatGPT/Codex desktop window was not found")
            self.keyboard.combo(VK_CONTROL, ord(str(slot.index + 1)))
            time.sleep(self.settle_seconds)
        current = self.capture_current()
        if current.session_id != slot.session_id:
            raise DesktopError(
                f"session verification failed: expected {slot.session_id!r}, "
                f"got {current.session_id!r}"
            )

    def close_page(self) -> None:
        """Hide the current thread view without closing the app."""
        if not self.window.minimize():
            raise DesktopError("ChatGPT/Codex desktop window was not found")

    def right_alt_down(self) -> None:
        self.keyboard.key_down(VK_RMENU)

    def right_alt_up(self) -> None:
        self.keyboard.key_up(VK_RMENU)

    def backspace(self) -> None:
        self._start_repeat(VK_BACK)

    def backspace_up(self) -> None:
        self._stop_repeat(VK_BACK)

    def delete(self) -> None:
        # Keep the old method name for callers while using the requested key.
        self.backspace()

    def left_down(self) -> None:
        self._start_repeat(VK_LEFT)

    def left_up(self) -> None:
        self._stop_repeat(VK_LEFT)

    def right_down(self) -> None:
        self._start_repeat(VK_RIGHT)

    def right_up(self) -> None:
        self._stop_repeat(VK_RIGHT)

    def send_enter(self) -> None:
        self._with_chat_focus(lambda: self.keyboard.combo(*self.send_hotkey))

    def release_all(self) -> None:
        self.right_alt_up()
        self.backspace_up()
        self.left_up()
        self.right_up()

    def _start_repeat(self, virtual_key: int) -> None:
        with self._repeat_lock:
            if virtual_key in self._repeat_controls:
                return
            stop = threading.Event()
            thread = threading.Thread(
                target=self._repeat_worker,
                args=(virtual_key, stop),
                name=f"key-repeat-{virtual_key:02x}",
                daemon=True,
            )
            self._repeat_controls[virtual_key] = (stop, thread)
        try:
            # Move once immediately, then repeat even if the target app does
            # not implement native key-held auto-repeat for injected input.
            self._with_chat_focus(lambda: self.keyboard.press(virtual_key))
            thread.start()
        except Exception:
            with self._repeat_lock:
                self._repeat_controls.pop(virtual_key, None)
            stop.set()
            raise

    def _stop_repeat(self, virtual_key: int) -> None:
        with self._repeat_lock:
            control = self._repeat_controls.pop(virtual_key, None)
        if control is None:
            return
        stop, thread = control
        stop.set()
        thread.join(timeout=0.2)

    def _repeat_worker(self, virtual_key: int, stop: threading.Event) -> None:
        try:
            if stop.wait(0.18):
                return
            while not stop.is_set():
                self.keyboard.press(virtual_key)
                if stop.wait(0.04):
                    return
        except Exception:
            LOGGER.exception("key repeat failed for virtual key 0x%02x", virtual_key)

    def _with_chat_focus(self, action) -> None:
        if not self.window.focus():
            raise DesktopError("ChatGPT/Codex desktop window was not found")
        action()
