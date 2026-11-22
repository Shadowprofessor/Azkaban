import json
import re
from io import BytesIO
from pathlib import Path
from threading import Lock


class LocalVoice:
    def __init__(self, model_path):
        self.path = Path(model_path) if model_path else None
        self._model = None
        self._lock = Lock()
        self.languages = self._read_languages()

    def _read_languages(self):
        if not self.path or not (self.path / "model.bin").is_file():
            return []
        try:
            tokenizer = json.loads((self.path / "tokenizer.json").read_text(encoding="utf-8"))
            return sorted(
                match.group(1) for token in tokenizer["added_tokens"]
                if (match := re.fullmatch(r"<\|([a-z]{2,3})\|>", token["content"]))
            )
        except (OSError, ValueError, KeyError, TypeError):
            return []

    @property
    def enabled(self):
        return bool(self.languages)

    def transcribe(self, audio, language=None):
        if not self.enabled:
            raise RuntimeError("Start GhostPrint with a downloaded multilingual Whisper model.")
        if language is not None and language not in self.languages:
            raise ValueError("Choose a dictation language supported by the local model.")
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError:
                    raise RuntimeError("Install faster-whisper in GhostPrint's Python environment.") from None
                self._model = WhisperModel(str(self.path), device="cpu", compute_type="int8", local_files_only=True)
            segments, info = self._model.transcribe(
                BytesIO(audio), beam_size=3, vad_filter=True, language=language
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            english = text
            if info.language != "en" and text:
                translated, _ = self._model.transcribe(
                    BytesIO(audio), beam_size=3, vad_filter=True, task="translate", language=info.language
                )
                english = " ".join(segment.text.strip() for segment in translated).strip()
            return {"text": text, "language": info.language, "lookup": english}
