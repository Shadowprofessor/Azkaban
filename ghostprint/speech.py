import ctypes as c
import os
import wave
from io import BytesIO
from pathlib import Path
from threading import Lock


class Voice(c.Structure):
    _fields_ = [("name", c.c_char_p), ("languages", c.c_char_p), ("identifier", c.c_char_p)]


CALLBACK = c.CFUNCTYPE(c.c_int, c.POINTER(c.c_short), c.c_int, c.c_void_p)
OUTPUT_SYNCHRONOUS = 2
INITIALIZE_DONT_EXIT = 0x8000
POSITION_CHARACTER = 1
CHARS_UTF8 = 1


class Speech:
    def __init__(self):
        self._lock = Lock()
        self._library = None
        self._voices = None
        self._callback = None

    def _initialize(self):
        if self._voices is not None:
            return
        self._voices = {}
        try:
            from espeakng_loader import get_data_path, get_library_path

            library = c.CDLL(get_library_path())
            data_directory = os.fsencode(Path(get_data_path()).parent)
        except (ImportError, OSError, RuntimeError):
            return
        library.espeak_Initialize.argtypes = [c.c_int, c.c_int, c.c_char_p, c.c_int]
        library.espeak_ListVoices.argtypes = [c.c_void_p]
        library.espeak_ListVoices.restype = c.POINTER(c.POINTER(Voice))
        library.espeak_SetVoiceByName.argtypes = [c.c_char_p]
        library.espeak_SetSynthCallback.argtypes = [CALLBACK]
        library.espeak_SetSynthCallback.restype = None
        library.espeak_Synth.argtypes = [c.c_char_p, c.c_size_t, c.c_uint, c.c_int,
                                         c.c_uint, c.c_uint, c.c_void_p, c.c_void_p]
        self._rate = library.espeak_Initialize(OUTPUT_SYNCHRONOUS, 0, data_directory, INITIALIZE_DONT_EXIT)
        if self._rate <= 0:
            return
        self._library = library
        for pointer in library.espeak_ListVoices(None):
            if not pointer:
                break
            voice = pointer.contents
            if voice.languages and voice.name:
                code = voice.languages[1:].decode("ascii", "ignore")
                if code:
                    self._voices.setdefault(code, voice.name)

    def languages(self):
        with self._lock:
            self._initialize()
            return sorted(self._voices)

    def render(self, text, language):
        with self._lock:
            self._initialize()
            voice = self._voices.get(language)
            if not voice or self._library.espeak_SetVoiceByName(voice) != 0:
                raise ValueError("Choose an available local read-aloud language.")
            encoded = text.encode("utf-8")
            pcm = []

            @CALLBACK
            def collect(samples, count, _events):
                if samples and count > 0:
                    pcm.append(c.string_at(samples, count * c.sizeof(c.c_short)))
                return 0

            self._callback = collect
            self._library.espeak_SetSynthCallback(collect)
            status = self._library.espeak_Synth(
                encoded, len(encoded) + 1, 0, POSITION_CHARACTER, 0, CHARS_UTF8, None, None
            )
            if status != 0 or not pcm:
                raise ValueError("The local voice could not read this prompt.")
            output = BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setparams((1, 2, self._rate, 0, "NONE", "not compressed"))
                wav.writeframes(b"".join(pcm))
            return output.getvalue()
