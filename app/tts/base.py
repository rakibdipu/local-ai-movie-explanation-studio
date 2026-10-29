"""Abstract base class and data models for Text-to-Speech synthesis."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class TTSProvider(ABC):
    """Abstract interface for all TTS engines."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def synthesize_to_file(
        self,
        text: str,
        output_file_path: str,
        language: str = "en",
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        pitch: int = 0
    ) -> str:
        """Synthesize text into an audio file (WAV / MP3) and return path."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether the TTS engine dependencies and models are functional."""
        pass

    @abstractmethod
    def get_default_voice(self, language: str, style: str = "cinematic_storytelling") -> str:
        """Get canonical voice identifier for language and style."""
        pass
