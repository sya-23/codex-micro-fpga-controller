from __future__ import annotations

import logging
import re
import subprocess
import threading

LOGGER = logging.getLogger(__name__)

_SPEECH_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice = $speaker.GetInstalledVoices() |
        Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN' } |
        Select-Object -First 1
    if (-not $voice) { throw "No zh-CN SAPI voice is installed" }
    $speaker.SelectVoice($voice.VoiceInfo.Name)
    $input = [Console]::OpenStandardInput()
    $reader = New-Object System.IO.StreamReader(
        $input,
        [System.Text.Encoding]::UTF8,
        $false
    )
    $text = $reader.ReadToEnd()
    $reader.Dispose()
    if ($text) { $speaker.Speak($text) }
} finally {
    $speaker.Dispose()
}
"""

_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_LIST_MARKER = re.compile(r"(?m)^\s*[-*+]\s+")
_HEADING_MARKER = re.compile(r"(?m)^\s*#{1,6}\s*")


def prepare_speech_text(text: str) -> str:
    """Keep natural-language reply text and remove markup/code noise."""
    text = _CODE_BLOCK.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _LIST_MARKER.sub("", text)
    text = _HEADING_MARKER.sub("", text)
    text = text.replace("**", "").replace("__", "")
    text = text.replace("|", "，")
    text = re.sub(r"[\\\[\]{}<>]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class WindowsSpeechSynthesizer:
    """Speak text through Windows SAPI without blocking the controller loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None

    def speak(self, text: str) -> bool:
        text = prepare_speech_text(text)
        if not text:
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            thread = threading.Thread(
                target=self._run,
                args=(text,),
                name="windows-tts",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        return True

    def stop(self) -> None:
        with self._lock:
            process = self._process
            thread = self._thread
        if process is not None and process.poll() is None:
            process.terminate()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def _run(self, text: str) -> None:
        process = None
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-Command", _SPEECH_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            with self._lock:
                self._process = process
            _stdout, stderr = process.communicate(text.encode("utf-8"))
            if process.returncode:
                message = stderr.decode("utf-8", errors="replace").strip()
                LOGGER.warning("Windows TTS failed: %s", message)
        except OSError:
            LOGGER.exception("could not start Windows TTS")
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
                self._thread = None
