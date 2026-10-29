"""Google Voice Engine Adapters for Gemini Native Audio and Google Cloud Text-to-Speech."""

import os
import re
import json
import base64
import urllib.request
import urllib.error
import subprocess
from typing import Dict, Any, List, Optional
from xml.sax.saxutils import escape as xml_escape

from app.tts.base import TTSProvider
from app.core.logger import get_logger
from app.core.models import DeliveryProfile

logger = get_logger()


class UnifiedVoiceAdapter:
    """Standardized interface for all voice providers."""

    def __init__(self, name: str):
        self.name = name

    def is_available(self) -> bool:
        raise NotImplementedError

    def list_voices(self, language: str = "en") -> List[Dict[str, Any]]:
        raise NotImplementedError

    def preview_voice(
        self,
        voice_id: str,
        sample_text: str,
        emotion: str,
        language: str,
        output_file: str,
        pronunciation_dict: Optional[Dict[str, str]] = None,
        pitch: Any = 0
    ) -> str:
        raise NotImplementedError

    def generate_segment(
        self,
        segment: Dict[str, Any],
        voice_config: Dict[str, Any],
        output_path: str,
        pronunciation_dict: Optional[Dict[str, str]] = None
    ) -> str:
        raise NotImplementedError

    def regenerate_segment(
        self,
        segment: Dict[str, Any],
        voice_config: Dict[str, Any],
        output_path: str,
        pronunciation_dict: Optional[Dict[str, str]] = None
    ) -> str:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        return self.generate_segment(segment, voice_config, output_path, pronunciation_dict)

    def validate_audio(self, file_path: str) -> Dict[str, Any]:
        """Validate synthesized audio file properties."""
        if not os.path.isfile(file_path):
            return {"valid": False, "error": "File does not exist", "duration": 0.0}
        size = os.path.getsize(file_path)
        if size < 500:
            return {"valid": False, "error": f"File too small ({size} bytes)", "duration": 0.0}

        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration,size,bit_rate:stream=codec_name,sample_rate,channels",
                "-of", "json", file_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            data = json.loads(res.stdout)
            fmt = data.get("format", {})
            stream = data.get("streams", [{}])[0]
            duration = float(fmt.get("duration", 0.0))
            return {
                "valid": duration > 0.1,
                "duration": duration,
                "sample_rate": int(stream.get("sample_rate", 44100)),
                "channels": int(stream.get("channels", 2)),
                "codec": stream.get("codec_name", "pcm_s16le"),
                "size_bytes": size
            }
        except Exception as exc:
            return {"valid": False, "error": str(exc), "duration": 0.0}


class GeminiTTSAdapter(UnifiedVoiceAdapter):
    """Gemini API Native TTS Adapter using Gemini 2.0 / 2.5 Flash multimodal audio synthesis."""

    GEMINI_VOICES = [
        {"id": "Puck", "name": "Puck", "gender": "male", "tone": "Conversational, youthful, engaging", "locales": ["en-US", "bn-BD", "hi-IN"]},
        {"id": "Charon", "name": "Charon", "gender": "male", "tone": "Deep, authoritative, cinematic", "locales": ["en-US", "bn-BD", "hi-IN"]},
        {"id": "Kore", "name": "Kore", "gender": "female", "tone": "Warm, empathetic, expressive", "locales": ["en-US", "bn-BD", "hi-IN"]},
        {"id": "Fenrir", "name": "Fenrir", "gender": "male", "tone": "Intense, dramatic, gritty", "locales": ["en-US", "bn-BD", "hi-IN"]},
        {"id": "Aoede", "name": "Aoede", "gender": "female", "tone": "Melodic, calm, documentary narrator", "locales": ["en-US", "bn-BD", "hi-IN"]}
    ]

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        super().__init__("gemini")
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def list_voices(self, language: str = "en") -> List[Dict[str, Any]]:
        return self.GEMINI_VOICES

    def _apply_pronunciation(self, text: str, pronunciation_dict: Optional[Dict[str, str]] = None) -> str:
        if not pronunciation_dict:
            return text
        result = text
        for word, phonetic in pronunciation_dict.items():
            pattern = r"\b" + re.escape(word) + r"\b"
            result = re.sub(pattern, phonetic, result)
        return result

    def _call_gemini_audio(self, spoken_text: str, emotion: str, voice_name: str, output_wav_path: str) -> str:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is not configured.")

        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"

        # Creative direction prompt strictly instructing the model not to speak instructions
        emotion_info = DeliveryProfile.get_profile(emotion)
        system_instruction = (
            f"You are a professional voice actor narrating a movie explanation. "
            f"Your delivery style must be {emotion_info['description']} "
            f"Speak with {emotion} emotion. Do NOT speak any introduction, outro, notes, or tags. "
            f"Only read the EXACT narration text provided."
        )

        prompt = (
            f"{system_instruction}\n\n"
            f"NARRATION TEXT TO SPEAK:\n{spoken_text}"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice_name
                        }
                    }
                }
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Extract audio content
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Gemini API returned no candidates: {data}")

        parts = candidates[0].get("content", {}).get("parts", [])
        audio_data_b64 = None
        mime_type = "audio/wav"

        for p in parts:
            inline = p.get("inlineData") or p.get("inline_data")
            if inline:
                audio_data_b64 = inline.get("data")
                mime_type = inline.get("mimeType", inline.get("mime_type", "audio/wav"))
                break

        if not audio_data_b64:
            raise RuntimeError(f"No audio data returned by Gemini model {self.model}")

        raw_bytes = base64.b64decode(audio_data_b64)
        temp_raw = output_wav_path + ".tmp.raw"
        with open(temp_raw, "wb") as f:
            f.write(raw_bytes)

        # Standardize audio to 44.1kHz 16-bit stereo PCM WAV via FFmpeg
        os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_raw,
            "-ar", "44100",
            "-ac", "2",
            "-acodec", "pcm_s16le",
            output_wav_path
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        finally:
            if os.path.exists(temp_raw):
                os.remove(temp_raw)

        return output_wav_path

    def preview_voice(
        self,
        voice_id: str,
        sample_text: str,
        emotion: str,
        language: str,
        output_file: str,
        pronunciation_dict: Optional[Dict[str, str]] = None,
        pitch: Any = 0
    ) -> str:
        processed_text = self._apply_pronunciation(sample_text, pronunciation_dict)
        return self._call_gemini_audio(processed_text, emotion, voice_id, output_file)

    def generate_segment(
        self,
        segment: Dict[str, Any],
        voice_config: Dict[str, Any],
        output_path: str,
        pronunciation_dict: Optional[Dict[str, str]] = None
    ) -> str:
        text = segment.get("clean_text") or segment.get("narration_text", "")
        processed_text = self._apply_pronunciation(text, pronunciation_dict)
        voice_id = voice_config.get("voice_id", "Puck")
        emotion = segment.get("emotion", DeliveryProfile.NORMAL_CONVERSATION)
        return self._call_gemini_audio(processed_text, emotion, voice_id, output_path)


class GoogleCloudTTSAdapter(UnifiedVoiceAdapter):
    """Google Cloud Text-to-Speech API Adapter with Journey, Neural2, Studio, and Wavenet voices."""

    VOICE_CATALOG = {
        "en": [
            {"id": "en-US-Journey-F", "name": "Journey Female", "gender": "female", "tier": "Journey (Conversational)"},
            {"id": "en-US-Journey-D", "name": "Journey Male", "gender": "male", "tier": "Journey (Conversational)"},
            {"id": "en-US-Neural2-J", "name": "Neural2 Male", "gender": "male", "tier": "Neural2"},
            {"id": "en-US-Neural2-F", "name": "Neural2 Female", "gender": "female", "tier": "Neural2"},
            {"id": "en-US-Studio-O", "name": "Studio Female", "gender": "female", "tier": "Studio (High Fidelity)"},
            {"id": "en-GB-Neural2-B", "name": "British Male", "gender": "male", "tier": "Neural2"}
        ],
        "bn": [
            {"id": "bn-IN-Wavenet-A", "name": "Wavenet Female (IN)", "gender": "female", "tier": "Wavenet"},
            {"id": "bn-IN-Wavenet-B", "name": "Wavenet Male (IN)", "gender": "male", "tier": "Wavenet"},
            {"id": "bn-BD-Wavenet-A", "name": "Wavenet Female (BD)", "gender": "female", "tier": "Wavenet"}
        ],
        "hi": [
            {"id": "hi-IN-Neural2-A", "name": "Neural2 Female", "gender": "female", "tier": "Neural2"},
            {"id": "hi-IN-Neural2-B", "name": "Neural2 Male", "gender": "male", "tier": "Neural2"},
            {"id": "hi-IN-Wavenet-A", "name": "Wavenet Female", "gender": "female", "tier": "Wavenet"},
            {"id": "hi-IN-Wavenet-B", "name": "Wavenet Male", "gender": "male", "tier": "Wavenet"}
        ]
    }

    def __init__(self, api_key: Optional[str] = None):
        super().__init__("google_cloud")
        self.api_key = api_key or os.environ.get("GOOGLE_CLOUD_API_KEY") or os.environ.get("GCP_TTS_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.endpoint = "https://texttospeech.googleapis.com/v1/text:synthesize"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def list_voices(self, language: str = "en") -> List[Dict[str, Any]]:
        lang = language.lower()
        return self.VOICE_CATALOG.get(lang, self.VOICE_CATALOG["en"])

    def _build_ssml(
        self,
        text: str,
        emotion: str,
        pacing: float = 1.0,
        pause_instructions: str = "",
        pronunciation_dict: Optional[Dict[str, str]] = None
    ) -> str:
        """Construct validated SSML with proper XML escaping and prosody."""
        # 1. Apply pronunciation dictionary
        processed = text
        if pronunciation_dict:
            for word, phonetic in pronunciation_dict.items():
                pattern = r"\b" + re.escape(word) + r"\b"
                processed = re.sub(pattern, f'<sub alias="{xml_escape(phonetic)}">{xml_escape(word)}</sub>', processed)

        # 2. XML escape non-tag content safely
        safe_text = xml_escape(processed)
        # Unescape any <sub alias="..."> tags we just placed
        safe_text = re.sub(r'&lt;sub alias=(?:"|&quot;)(.*?)(?:"|&quot;)&gt;(.*?)&lt;/sub&gt;', r'<sub alias="\1">\2</sub>', safe_text)

        # Pacing calculation
        rate_pct = int(round((pacing - 1.0) * 100))
        rate_str = f"{rate_pct:+d}%" if rate_pct != 0 else "default"

        # Optional pause insertion at paragraph or sentence breaks
        break_tag = '<break time="300ms"/>' if "pause" in pause_instructions.lower() else ""

        ssml = (
            f'<speak>'
            f'<prosody rate="{rate_str}">'
            f'{safe_text}'
            f'{break_tag}'
            f'</prosody>'
            f'</speak>'
        )
        return ssml

    def _call_cloud_tts(self, ssml: str, voice_id: str, language: str, output_wav_path: str) -> str:
        if not self.api_key:
            raise RuntimeError("GOOGLE_CLOUD_API_KEY is not configured.")

        url = f"{self.endpoint}?key={self.api_key}"
        # Derive language code from voice_id
        lang_code = "-".join(voice_id.split("-")[:2]) if "-" in voice_id else "en-US"

        payload = {
            "input": {"ssml": ssml},
            "voice": {
                "languageCode": lang_code,
                "name": voice_id
            },
            "audioConfig": {
                "audioEncoding": "LINEAR16",
                "sampleRateHertz": 44100
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        audio_b64 = data.get("audioContent")
        if not audio_b64:
            raise RuntimeError(f"Google Cloud TTS returned no audioContent: {data}")

        os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)
        raw_bytes = base64.b64decode(audio_b64)
        with open(output_wav_path, "wb") as f:
            f.write(raw_bytes)

        return output_wav_path

    def preview_voice(
        self,
        voice_id: str,
        sample_text: str,
        emotion: str,
        language: str,
        output_file: str,
        pronunciation_dict: Optional[Dict[str, str]] = None,
        pitch: Any = 0
    ) -> str:
        prof = DeliveryProfile.get_profile(emotion)
        ssml = self._build_ssml(sample_text, emotion, pacing=prof["pacing"], pronunciation_dict=pronunciation_dict)
        return self._call_cloud_tts(ssml, voice_id, language, output_file)

    def generate_segment(
        self,
        segment: Dict[str, Any],
        voice_config: Dict[str, Any],
        output_path: str,
        pronunciation_dict: Optional[Dict[str, str]] = None
    ) -> str:
        text = segment.get("clean_text") or segment.get("narration_text", "")
        voice_id = voice_config.get("voice_id", "en-US-Journey-F")
        emotion = segment.get("emotion", DeliveryProfile.NORMAL_CONVERSATION)
        pacing = float(segment.get("pacing", 1.0))
        pause_inst = segment.get("pause_instructions", "")
        lang = voice_config.get("language", "en")

        ssml = self._build_ssml(
            text=text,
            emotion=emotion,
            pacing=pacing,
            pause_instructions=pause_inst,
            pronunciation_dict=pronunciation_dict
        )
        return self._call_cloud_tts(ssml, voice_id, lang, output_path)


class EdgeTTSAdapter(UnifiedVoiceAdapter):
    """Neural Edge-TTS Adapter wrapped into the UnifiedVoiceAdapter interface."""

    VOICE_CATALOG = {
        "en": [
            {"id": "en-US-ChristopherNeural", "name": "Christopher (US Male - Cinematic)", "gender": "male", "tier": "Neural"},
            {"id": "en-US-JennyNeural", "name": "Jenny (US Female - Warm)", "gender": "female", "tier": "Neural"},
            {"id": "en-US-GuyNeural", "name": "Guy (US Male - Casual/Fast)", "gender": "male", "tier": "Neural"},
            {"id": "en-GB-RyanNeural", "name": "Ryan (UK Male - Mystery/Detective)", "gender": "male", "tier": "Neural"},
            {"id": "en-US-EricNeural", "name": "Eric (US Male - Serious Documentary)", "gender": "male", "tier": "Neural"}
        ],
        "bn": [
            {"id": "bn-BD-PradeepNeural", "name": "Pradeep (BD Male - Natural Storyteller)", "gender": "male", "tier": "Neural"},
            {"id": "bn-BD-NabanitaNeural", "name": "Nabanita (BD Female - Expressive)", "gender": "female", "tier": "Neural"},
            {"id": "bn-IN-BashkarNeural", "name": "Bashkar (IN Male - Clear Articulate)", "gender": "male", "tier": "Neural"}
        ],
        "hi": [
            {"id": "hi-IN-MadhurNeural", "name": "Madhur (IN Male - Cinematic)", "gender": "male", "tier": "Neural"},
            {"id": "hi-IN-SwaraNeural", "name": "Swara (IN Female - Clear/Engaging)", "gender": "female", "tier": "Neural"}
        ]
    }

    def __init__(self):
        super().__init__("edge-tts")
        from app.tts.edge_tts_provider import EdgeTTSProvider
        self._provider = EdgeTTSProvider()

    def is_available(self) -> bool:
        return self._provider.is_available()

    def list_voices(self, language: str = "en") -> List[Dict[str, Any]]:
        lang = language.lower()
        return self.VOICE_CATALOG.get(lang, self.VOICE_CATALOG["en"])

    def preview_voice(
        self,
        voice_id: str,
        sample_text: str,
        emotion: str,
        language: str,
        output_file: str,
        pronunciation_dict: Optional[Dict[str, str]] = None,
        pitch: Any = 0
    ) -> str:
        prof = DeliveryProfile.get_profile(emotion)
        speed = prof["pacing"]
        return self._provider.synthesize_to_file(
            text=sample_text,
            output_file_path=output_file,
            language=language,
            voice_id=voice_id,
            speed=speed,
            pitch=pitch
        )

    def generate_segment(
        self,
        segment: Dict[str, Any],
        voice_config: Dict[str, Any],
        output_path: str,
        pronunciation_dict: Optional[Dict[str, str]] = None
    ) -> str:
        text = segment.get("clean_text") or segment.get("narration_text", "")
        # Apply pronunciation dictionary replacements
        if pronunciation_dict:
            for word, phonetic in pronunciation_dict.items():
                pattern = r"\b" + re.escape(word) + r"\b"
                text = re.sub(pattern, phonetic, text)

        voice_id = voice_config.get("voice_id")
        lang = voice_config.get("language", "en")
        pacing = float(segment.get("pacing", 1.0))
        pitch = voice_config.get("pitch", 0)

        return self._provider.synthesize_to_file(
            text=text,
            output_file_path=output_path,
            language=lang,
            voice_id=voice_id,
            speed=pacing,
            pitch=pitch
        )


class FallbackVoiceAdapter(UnifiedVoiceAdapter):
    """System / Offline TTS Adapter for zero-network execution and testing."""

    def __init__(self):
        super().__init__("system")
        from app.tts.fallback_provider import FallbackTTSProvider
        self._provider = FallbackTTSProvider()

    def is_available(self) -> bool:
        return True

    def list_voices(self, language: str = "en") -> List[Dict[str, Any]]:
        return [
            {"id": "default", "name": f"System Default Voice ({language.upper()})", "gender": "neutral", "tier": "Offline Fallback"}
        ]

    def preview_voice(
        self,
        voice_id: str,
        sample_text: str,
        emotion: str,
        language: str,
        output_file: str,
        pronunciation_dict: Optional[Dict[str, str]] = None
    ) -> str:
        return self._provider.synthesize_to_file(sample_text, output_file, language=language)

    def generate_segment(
        self,
        segment: Dict[str, Any],
        voice_config: Dict[str, Any],
        output_path: str,
        pronunciation_dict: Optional[Dict[str, str]] = None
    ) -> str:
        text = segment.get("clean_text") or segment.get("narration_text", "")
        lang = voice_config.get("language", "en")
        return self._provider.synthesize_to_file(text, output_path, language=lang)


def get_voice_adapter(preferred_provider: str = "auto") -> UnifiedVoiceAdapter:
    """Factory creating the appropriate unified voice adapter with graceful fallback."""
    p = preferred_provider.lower()

    if p == "gemini":
        adapter = GeminiTTSAdapter()
        if adapter.is_available():
            logger.info("Using Gemini Native TTS Voice Adapter (Gemini 2.0/2.5 Flash)")
            return adapter
        logger.warning("Gemini API key not found. Falling back to Edge-TTS adapter.")

    elif p in ("google_cloud", "google", "gcp"):
        adapter = GoogleCloudTTSAdapter()
        if adapter.is_available():
            logger.info("Using Google Cloud Text-to-Speech Adapter")
            return adapter
        logger.warning("Google Cloud TTS API key not found. Falling back to Edge-TTS adapter.")

    elif p == "auto":
        gemini_adapter = GeminiTTSAdapter()
        if gemini_adapter.is_available():
            logger.info("Auto-detected Gemini API key: Using Gemini Native TTS Voice Adapter")
            return gemini_adapter

        cloud_adapter = GoogleCloudTTSAdapter()
        if cloud_adapter.is_available():
            logger.info("Auto-detected Google Cloud key: Using Google Cloud Text-to-Speech Adapter")
            return cloud_adapter

    # Default to Edge-TTS neural provider
    edge_adapter = EdgeTTSAdapter()
    if edge_adapter.is_available():
        logger.info("Using Edge-TTS Neural Voice Adapter (English, Bangla, Hindi)")
        return edge_adapter

    logger.info("Using Fallback / Offline System Voice Adapter")
    return FallbackVoiceAdapter()
