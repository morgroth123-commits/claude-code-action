from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.voice import LocalVoice


class VoiceTest(unittest.TestCase):
    def test_tts_builds_hidden_local_powershell_command(self) -> None:
        calls = []
        voice = LocalVoice(runner=lambda argv, **kwargs: calls.append((argv, kwargs)) or 0)
        voice.speak("hello Vader")
        argv, options = calls[0]
        self.assertIn("powershell", Path(argv[0]).name.casefold())
        self.assertTrue(options.get("hidden"))
        self.assertNotIn("hello Vader", " ".join(argv))

    def test_transcription_reports_missing_local_whisper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.wav"
            audio.write_bytes(b"RIFF")
            voice = LocalVoice(whisper_executable=None, whisper_model=None)
            self.assertFalse(voice.transcription_health()["ready"])
            with self.assertRaisesRegex(RuntimeError, "local Whisper"):
                voice.transcribe(audio)


if __name__ == "__main__":
    unittest.main()
