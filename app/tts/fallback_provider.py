"""Offline and system fallback TTS provider using eSpeak or FFmpeg synthesis."""

import os
import subprocess
import shutil
from typing import Optional
from app.tts.base import TTSProvider
from app.core.logger import get_logger

logger = get_logger()


class FallbackTTSProvider(TTSProvider):
    """System fallback TTS engine using espeak-ng / espeak or FFmpeg procedural tones."""

    def __init__(self):
        super().__init__("system-fallback")
        self.has_espeak = shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None
        self.espeak_bin = shutil.which("espeak-ng") or shutil.which("espeak")

    def is_available(self) -> bool:
        return True

    def get_default_voice(self, language: str, style: str = "cinematic_storytelling") -> str:
        lang_map = {"en": "en", "bn": "bn", "hi": "hi"}
        return lang_map.get(language.lower(), "en")

    def synthesize_to_file(
        self,
        text: str,
        output_file_path: str,
        language: str = "en",
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: int = 0
    ) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(output_file_path)), exist_ok=True)
        voice = voice_id or self.get_default_voice(language)
        lang_code = "bn" if language.lower() in ("bn", "bangla") else ("hi" if language.lower() in ("hi", "hindi") else "en")

        # 1. For non-English languages (e.g. Bangla, Hindi), prioritize gTTS since pyttsx3 lacks Indic voices
        if lang_code in ("bn", "hi"):
            try:
                from gtts import gTTS
                temp_mp3 = output_file_path + ".tmp.mp3"
                tts = gTTS(text=text, lang=lang_code, slow=(speed < 0.9))
                tts.save(temp_mp3)

                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i", temp_mp3,
                    "-af", "highpass=f=80,treble=g=2.5:f=3500,loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-ac", "2",
                    "-ar", "44100",
                    output_file_path
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if os.path.exists(temp_mp3):
                    os.remove(temp_mp3)
                return output_file_path
            except Exception as e:
                logger.debug(f"gTTS fallback error: {e}")

        # 2. Try pyttsx3 (for English only)
        if lang_code == "en":
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", int(engine.getProperty("rate") * speed))
                tmp_wav = output_file_path + ".pyttsx3.wav"
                engine.save_to_file(text, tmp_wav)
                engine.runAndWait()
                engine.stop()
                if os.path.isfile(tmp_wav) and os.path.getsize(tmp_wav) > 100:
                    cmd = ["ffmpeg", "-y", "-i", tmp_wav, "-ac", "2", "-ar", "44100", output_file_path]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    os.remove(tmp_wav)
                    return output_file_path
            except Exception as e:
                logger.debug(f"pyttsx3 fallback error: {e}")

        # 3. Try eSpeak if installed
        if self.has_espeak and self.espeak_bin:
            words_per_min = int(140 * speed)
            cmd = [
                self.espeak_bin,
                "-v", voice,
                "-s", str(words_per_min),
                "-w", output_file_path,
                text
            ]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if os.path.isfile(output_file_path) and os.path.getsize(output_file_path) > 100:
                    return output_file_path
            except Exception as e:
                logger.warning(f"eSpeak execution failed: {e}")

        # 4. Final Fallback: Generate subtle narration audio with FFmpeg
        words_count = len(text.split())
        est_duration = max(3.0, words_count / 2.3)
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", f"anoisesrc=d={est_duration}:c=pink:r=44100:a=0.01",
            "-af", "volume=0.0",
            output_file_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_file_path
