from __future__ import annotations

import logging
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
    if ($voice) { $speaker.SelectVoice($voice.VoiceInfo.Name) }
    $text = [Console]::In.ReadToEnd()
    if ($text) { $speaker.Speak($text) }
} finally {
    $speaker.Dispose()
}
"""


class WindowsSpeechSynthesizer:
    """Speak text through Windows SAPI without blocking the controller loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None

    def speak(self, text: str) -> bool:
        text = text.strip()
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
                text=True,
                encoding="utf-8",
                creationflags=creationflags,
            )
            with self._lock:
                self._process = process
            _stdout, stderr = process.communicate(text)
            if process.returncode:
                LOGGER.warning("Windows TTS failed: %s", stderr.strip())
        except OSError:
            LOGGER.exception("could not start Windows TTS")
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
                self._thread = None
