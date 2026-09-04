"""Local Windows speech adapters with no cloud fallback."""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable


Runner = Callable[..., Any]


def _default_runner(argv: list[str], *, hidden: bool = True, timeout: int = 120) -> Any:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if hidden else 0
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=flags,
        check=False,
    )


class LocalVoice:
    def __init__(
        self,
        *,
        runner: Runner | None = None,
        whisper_executable: Path | str | None = None,
        whisper_model: Path | str | None = None,
    ) -> None:
        self.runner = runner or _default_runner
        self.whisper_executable = self._resolve_whisper(whisper_executable)
        self.whisper_model = None if whisper_model is None else Path(whisper_model).expanduser().resolve()

    def speak(self, text: str) -> None:
        value = str(text).strip()
        if not value:
            raise ValueError("Speech text cannot be blank.")
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        script = (
            "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($args[0]));"
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$s.Speak($t);$s.Dispose()"
        )
        result = self.runner(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script, encoded],
            hidden=True,
            timeout=120,
        )
        code = int(getattr(result, "returncode", result if isinstance(result, int) else 0))
        if code != 0:
            raise RuntimeError(f"Local Windows TTS failed with exit code {code}.")

    def transcription_health(self) -> dict[str, Any]:
        ready = bool(
            self.whisper_executable
            and Path(self.whisper_executable).is_file()
            and self.whisper_model
            and self.whisper_model.is_file()
        )
        return {
            "ready": ready,
            "executable": None if self.whisper_executable is None else str(self.whisper_executable),
            "model": None if self.whisper_model is None else str(self.whisper_model),
            "mode": "local-only",
        }

    def transcribe(self, audio_path: Path) -> str:
        health = self.transcription_health()
        if not health["ready"]:
            raise RuntimeError("A local Whisper executable and model are required; ChatMPD will not send audio to a cloud service.")
        audio = Path(audio_path).expanduser().resolve()
        if not audio.is_file():
            raise FileNotFoundError(audio)
        prefix = audio.with_name(audio.stem + ".chatmpd-transcript")
        result = self.runner(
            [str(self.whisper_executable), "-m", str(self.whisper_model), "-f", str(audio), "-otxt", "-of", str(prefix)],
            hidden=True,
            timeout=3600,
        )
        code = int(getattr(result, "returncode", result if isinstance(result, int) else 0))
        if code != 0:
            raise RuntimeError(f"Local Whisper transcription failed with exit code {code}.")
        output = prefix.with_suffix(prefix.suffix + ".txt")
        if not output.is_file():
            raise RuntimeError("Local Whisper completed without a transcript file.")
        return output.read_text(encoding="utf-8", errors="replace").strip()

    @staticmethod
    def _resolve_whisper(value: Path | str | None) -> Path | None:
        if value is not None:
            return Path(value).expanduser().resolve()
        for name in ("whisper-cli.exe", "whisper-cli", "main.exe", "main"):
            found = shutil.which(name)
            if found:
                return Path(found).resolve()
        return None
