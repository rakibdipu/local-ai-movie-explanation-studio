"""Edge-TTS provider implementation supporting neural English, Bangla, and Hindi voices."""

import os
import asyncio
import subprocess
from typing import Dict, Any, Optional
import edge_tts
from app.tts.base import TTSProvider
from app.core.logger import get_logger

logger = get_logger()

# Default speech rate boost per language (Edge-TTS rate parameter).
# Bangla/Hindi neural voices naturally speak slower than English, so we boost them.
DEFAULT_RATE = {
    "en": {
        "cinematic_storytelling": "+0%",
        "fast_paced_youtube": "+8%",
        "serious_documentary": "+0%",
        "mystery_detective": "-3%",
        "casual_storyteller": "+5%",
        "default": "+0%"
    },
    "bn": {
        "cinematic_storytelling": "+5%",
        "fast_paced_youtube": "+8%",
        "serious_documentary": "+4%",
        "mystery_detective": "+2%",
        "casual_storyteller": "+5%",
        "default": "+5%"
    },
    "hi": {
        "cinematic_storytelling": "+0%",
        "fast_paced_youtube": "+6%",
        "serious_documentary": "+0%",
        "mystery_detective": "-2%",
        "casual_storyteller": "+4%",
        "default": "+0%"
    }
}

DEFAULT_VOICES = {
    "en": {
        "cinematic_storytelling": "en-US-ChristopherNeural",
        "fast_paced_youtube": "en-US-GuyNeural",
        "serious_documentary": "en-US-EricNeural",
        "mystery_detective": "en-GB-RyanNeural",
        "casual_storyteller": "en-US-GuyNeural",
        "default": "en-US-ChristopherNeural"
    },
    "bn": {
        "cinematic_storytelling": "bn-BD-PradeepNeural",
        "fast_paced_youtube": "bn-BD-PradeepNeural",
        "serious_documentary": "bn-BD-PradeepNeural",
        "mystery_detective": "bn-BD-PradeepNeural",
        "casual_storyteller": "bn-BD-NabanitaNeural",
        "default": "bn-BD-PradeepNeural"
    },
    "hi": {
        "cinematic_storytelling": "hi-IN-MadhurNeural",
        "fast_paced_youtube": "hi-IN-MadhurNeural",
        "serious_documentary": "hi-IN-MadhurNeural",
        "mystery_detective": "hi-IN-MadhurNeural",
        "casual_storyteller": "hi-IN-SwaraNeural",
        "default": "hi-IN-MadhurNeural"
    }
}

DEFAULT_PITCH = {
    "en": {
        "cinematic_storytelling": "-2Hz",
        "fast_paced_youtube": "+0Hz",
        "serious_documentary": "-3Hz",
        "mystery_detective": "-4Hz",
        "casual_storyteller": "+0Hz",
        "default": "+0Hz"
    },
    "bn": {
        "cinematic_storytelling": "-8Hz",
        "fast_paced_youtube": "-6Hz",
        "serious_documentary": "-10Hz",
        "mystery_detective": "-10Hz",
        "casual_storyteller": "-6Hz",
        "default": "-8Hz"
    },
    "hi": {
        "cinematic_storytelling": "-3Hz",
        "fast_paced_youtube": "+0Hz",
        "serious_documentary": "-4Hz",
        "mystery_detective": "-5Hz",
        "casual_storyteller": "+0Hz",
        "default": "+0Hz"
    }
}

def get_default_rate(language: str, style: str = "cinematic_storytelling") -> str:
    """Get the default Edge-TTS rate string for the given language and style."""
    lang_dict = DEFAULT_RATE.get(language.lower(), DEFAULT_RATE["en"])
    return lang_dict.get(style, lang_dict["default"])

def get_default_pitch(language: str, style: str = "cinematic_storytelling") -> str:
    """Get the default Edge-TTS pitch string for the given language and style."""
    lang_dict = DEFAULT_PITCH.get(language.lower(), DEFAULT_PITCH["en"])
    return lang_dict.get(style, lang_dict["default"])


class EdgeTTSProvider(TTSProvider):
    """High-quality neural TTS provider via Edge-TTS."""

    def __init__(self):
        super().__init__("edge-tts")

    def is_available(self) -> bool:
        return True

    def get_default_voice(self, language: str, style: str = "cinematic_storytelling") -> str:
        lang_dict = DEFAULT_VOICES.get(language.lower(), DEFAULT_VOICES["en"])
        return lang_dict.get(style, lang_dict["default"])

    def synthesize_to_file(
        self,
        text: str,
        output_file_path: str,
        language: str = "en",
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: Any = 0
    ) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(output_file_path)), exist_ok=True)
        voice = voice_id or self.get_default_voice(language)
        style = "cinematic_storytelling"
        
        # Use language-aware default rate when speed is 1.0 (no manual override)
        if speed == 1.0:
            rate_str = get_default_rate(language, style)
        else:
            rate_diff = int(round((speed - 1.0) * 100))
            rate_str = f"{rate_diff:+d}%"

        # Resolve pitch string (support int Hz, string with units, or default)
        if pitch is not None and str(pitch).strip() not in ["0", "+0Hz", "0Hz", "default", ""]:
            p_val = str(pitch).strip()
            if p_val.endswith(("%", "Hz", "st")):
                pitch_str = p_val
            else:
                try:
                    pitch_str = f"{int(float(p_val)):+d}Hz"
                except Exception:
                    pitch_str = get_default_pitch(language, style)
        else:
            pitch_str = get_default_pitch(language, style)

        temp_mp3 = output_file_path if output_file_path.endswith(".mp3") else f"{output_file_path}.tmp.mp3"

        async def _run_synthesis():
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate_str, pitch=pitch_str)
            await asyncio.wait_for(communicate.save(temp_mp3), timeout=45.0)

        import time
        last_error = None
        for attempt in range(1, 4):
            try:
                asyncio.run(_run_synthesis())
                last_error = None
                break
            except Exception as e:
                last_error = e
                logger.warning(f"Edge-TTS attempt {attempt}/3 for voice {voice} ({e}), retrying in {attempt * 1.5}s...")
                time.sleep(attempt * 1.5)

        if last_error:
            logger.warning(f"Edge-TTS synthesis error for voice {voice} after 3 attempts ({last_error}), trying fallback...")
            raise last_error

        # Convert to WAV with rich chest baritone mastering if output_file_path is .wav
        if output_file_path.endswith(".wav"):
            cmd = [
                "ffmpeg",
                "-y",
                "-i", temp_mp3,
                "-af", "bass=g=3.0:f=150,equalizer=f=220:width_type=q:width=1.2:g=2.0,treble=g=-0.5:f=4000,loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ac", "2",
                "-ar", "44100",
                output_file_path
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if os.path.exists(temp_mp3) and temp_mp3 != output_file_path:
                os.remove(temp_mp3)

        return output_file_path
