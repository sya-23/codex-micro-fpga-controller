from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .slots import SlotStatus

LOGGER = logging.getLogger(__name__)

_AGE_SUFFIX = re.compile(
    r"(?P<title>.*?)(?P<age>\d+\s*(?:mo|s|m|h|d|w|y)|\d{1,2}:\d{2})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConversationObservation:
    title: str
    status: SlotStatus
    observed_at: float
    raw_name: str = ""


def normalize_title(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def split_title_age(value: str) -> tuple[str, bool]:
    value = " ".join(value.strip().split())
    match = _AGE_SUFFIX.match(value)
    if match is None:
        return value, False
    title = match.group("title").rstrip()
    return title, bool(title)


def classify_icon_pixels(pixels: Iterable[tuple[int, int, int]]) -> SlotStatus:
    """Classify the small right-side status icon without fixed screen coords."""
    pixels = list(pixels)
    if not pixels:
        return SlotStatus.UNKNOWN

    foreground = [
        pixel
        for pixel in pixels
        if max(pixel) > 80 and max(pixel) - min(pixel) > 22
    ]
    if not foreground:
        return SlotStatus.UNKNOWN

    blue = [
        pixel
        for pixel in foreground
        if pixel[2] - pixel[0] >= 55 and pixel[2] - pixel[1] >= 25
    ]
    if len(blue) / len(pixels) >= 0.02:
        return SlotStatus.COMPLETED
    return SlotStatus.RUNNING


class ChatGPTListReader:
    """Read conversation states through Windows UI Automation.

    The reader never clicks, scrolls, or relies on absolute screen positions.
    The UIA ListItem supplies the conversation row and its status Image supplies
    the relative icon rectangle; pixels are used only inside that rectangle.
    """

    def __init__(
        self,
        window_factory: Callable[[], object] | None = None,
        screen_capture: Callable[[object], object] | None = None,
    ) -> None:
        self._window_factory = window_factory
        self._screen_capture = screen_capture

    def read(self) -> list[ConversationObservation]:
        window = self._get_window()
        if window is None:
            return []
        now = time.monotonic()
        observations: list[ConversationObservation] = []
        for item in window.descendants(control_type="ListItem"):
            if item.descendants(control_type="ListItem"):
                continue
            raw_name = self._safe_name(item)
            if not raw_name:
                continue
            title, has_age = split_title_age(raw_name)
            if not title:
                continue
            status = self._item_status(item, has_age)
            observations.append(
                ConversationObservation(
                    title=title,
                    status=status,
                    observed_at=now,
                    raw_name=raw_name,
                )
            )
        return observations

    def _get_window(self):
        if self._window_factory is not None:
            return self._window_factory()
        try:
            from pywinauto import Desktop

            windows = Desktop(backend="uia").windows()
            for window in windows:
                if self._safe_window_name(window).casefold() == "chatgpt":
                    return window
        except Exception:
            LOGGER.exception("ChatGPT UI Automation read failed")
        return None

    def _item_status(self, item, has_age: bool) -> SlotStatus:
        item_rect = item.rectangle()
        status_images = []
        for image in item.descendants(control_type="Image"):
            if image.element_info.class_name != "icon-xs shrink-0":
                continue
            rect = image.rectangle()
            if rect.right >= item_rect.right - 70 and rect.bottom > item_rect.top:
                status_images.append(image)
        if status_images:
            image = status_images[-1]
            try:
                return self._classify_image(image.rectangle())
            except Exception:
                LOGGER.debug("status icon capture failed", exc_info=True)
                return SlotStatus.UNKNOWN
        return SlotStatus.IDLE if has_age else SlotStatus.UNKNOWN

    def _classify_image(self, rect) -> SlotStatus:
        capture = self._screen_capture or self._capture_screen
        pixels = capture(rect)
        if hasattr(pixels, "convert"):
            pixels = pixels.convert("RGB")
            pixels = list(pixels.getdata())
        return classify_icon_pixels(pixels)

    @staticmethod
    def _capture_screen(rect):
        from PIL import ImageGrab

        return ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))

    @staticmethod
    def _safe_name(element) -> str:
        try:
            return str(element.element_info.name or "")
        except Exception:
            return ""

    @staticmethod
    def _safe_window_name(element) -> str:
        try:
            return str(element.window_text() or "")
        except Exception:
            return ""


class ChatGPTStatusMonitor:
    def __init__(self, controller, interval: float = 0.8) -> None:
        self.controller = controller
        self.interval = max(0.25, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="chatgpt-status-monitor",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info("ChatGPT list status monitor started (interval=%.2fs)", self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        reader = ChatGPTListReader()
        while not self._stop.is_set():
            try:
                observations = reader.read()
                if observations:
                    self.controller.observe_conversations(observations)
            except Exception:
                LOGGER.exception("ChatGPT list status monitor failed")
            self._stop.wait(self.interval)
