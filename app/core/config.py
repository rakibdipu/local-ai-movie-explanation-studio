"""Configuration loading and natural language prompt parsing."""

import os
import re
import yaml
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple


LANGUAGE_ALIASES = {
    "english": "en",
    "en": "en",
    "eng": "en",
    "ইংরেজি": "en",
    "bangla": "bn",
    "bengali": "bn",
    "bn": "bn",
    "বাংলা": "bn",
    "hindi": "hi",
    "hi": "hi",
    "hin": "hi",
    "হিন্দি": "hi",
    "हिंदी": "hi",
}

LANGUAGE_NAMES = {
    "en": "English",
    "bn": "Bangla",
    "hi": "Hindi",
}

STYLE_ALIASES = {
    "cinematic": "cinematic_storytelling",
    "cinematic_storytelling": "cinematic_storytelling",
    "storyteller": "cinematic_storytelling",
    "storytelling": "cinematic_storytelling",
    "cinematic storyteller": "cinematic_storytelling",
    "fast": "fast_paced_youtube",
    "fast-paced": "fast_paced_youtube",
    "fast_paced": "fast_paced_youtube",
    "fast_paced_youtube": "fast_paced_youtube",
    "youtube": "fast_paced_youtube",
    "fast-paced youtube narrator": "fast_paced_youtube",
    "documentary": "serious_documentary",
    "serious": "serious_documentary",
    "serious_documentary": "serious_documentary",
    "serious documentary": "serious_documentary",
    "mystery": "mystery_detective",
    "detective": "mystery_detective",
    "mystery_detective": "mystery_detective",
    "mystery / detective": "mystery_detective",
    "casual": "casual_storyteller",
    "casual_storyteller": "casual_storyteller",
    "casual storyteller": "casual_storyteller",
}

STYLE_NAMES = {
    "cinematic_storytelling": "Cinematic storyteller",
    "fast_paced_youtube": "Fast-paced YouTube narrator",
    "serious_documentary": "Serious documentary",
    "mystery_detective": "Mystery / detective",
    "casual_storyteller": "Casual storyteller",
}


@dataclass
class ExplanationParams:
    """User parameters for a movie explanation session."""
    language: str = "en"
    duration_minutes: int = 20
    narration_style: str = "cinematic_storytelling"
    aspect_ratio: str = "16:9"
    resolution: str = "1280x720"
    tone: Optional[str] = None
    custom_instructions: Optional[str] = None
    # Extra languages to generate for YouTube multi-language audio tracks
    # e.g. ["bn", "hi"] means also generate Bangla + Hindi alongside primary
    extra_languages: field(default_factory=list) = None

    def __post_init__(self):
        if self.extra_languages is None:
            self.extra_languages = []

    @property
    def all_languages(self) -> list:
        """Primary language + all extra languages, deduplicated."""
        seen = {self.language}
        result = [self.language]
        for lang in (self.extra_languages or []):
            if lang not in seen:
                seen.add(lang)
                result.append(lang)
        return result

    @property
    def language_name(self) -> str:
        return LANGUAGE_NAMES.get(self.language, self.language.title())

    @property
    def style_name(self) -> str:
        return STYLE_NAMES.get(self.narration_style, self.narration_style.replace("_", " ").title())


def parse_natural_prompt(prompt_text: str, default_duration: int = 20) -> ExplanationParams:
    """Parse natural language instruction into structured explanation parameters.
    
    Examples:
        - "Create a 20 minute Hindi movie explanation"
        - "Explain this movie in English in approximately 18 minutes"
        - "Bangla, cinematic storytelling, 20 minutes"
        - "9:16 short format fast-paced recap in English for 10 min"
    """
    params = ExplanationParams()
    if not prompt_text:
        return params

    text = prompt_text.lower()

    # 1. Parse Language
    for alias, code in LANGUAGE_ALIASES.items():
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            params.language = code
            break

    # 2. Parse Duration (minutes)
    duration_match = re.search(r"(\d+)\s*(?:minutes?|mins?|m\b|মিনিট|मिनट)", text, re.IGNORECASE)
    if duration_match:
        try:
            val = int(duration_match.group(1))
            if 1 <= val <= 180:
                params.duration_minutes = val
        except ValueError:
            params.duration_minutes = default_duration
    else:
        # Check standalone numbers like "20m" or "15 minute"
        num_match = re.search(r"\b(\d+)\s*m\b", text, re.I)
        if num_match:
            params.duration_minutes = int(num_match.group(1))
        else:
            params.duration_minutes = default_duration

    # 3. Parse Narration Style
    matched_style = None
    for alias, canonical in STYLE_ALIASES.items():
        if alias in text:
            matched_style = canonical
            break
    if matched_style:
        params.narration_style = matched_style

    # 4. Parse Aspect Ratio
    if "9:16" in text or "vertical" in text or "shorts" in text or "reels" in text or "tiktok" in text:
        params.aspect_ratio = "9:16"
        params.resolution = "720x1280"
    elif "1:1" in text or "square" in text:
        params.aspect_ratio = "1:1"
        params.resolution = "720x720"
    elif "16:9" in text or "horizontal" in text or "widescreen" in text:
        params.aspect_ratio = "16:9"
        params.resolution = "1280x720"

    # 5. Parse Resolution overrides (1080p / 720p)
    if "1080p" in text or "1920x1080" in text or "fhd" in text:
        if params.aspect_ratio == "16:9":
            params.resolution = "1920x1080"
        elif params.aspect_ratio == "9:16":
            params.resolution = "1080x1920"
    elif "720p" in text or "1280x720" in text or "hd" in text:
        if params.aspect_ratio == "16:9":
            params.resolution = "1280x720"

    params.custom_instructions = prompt_text.strip()
    return params


class Config:
    """Global configuration loader and accessor."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = os.path.abspath(config_path)
        self.data: Dict[str, Any] = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if os.path.isfile(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def get(self, key_path: str, default: Any = None) -> Any:
        """Access nested config using dot notation (e.g. 'video.fps')."""
        keys = key_path.split(".")
        val = self.data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    @property
    def input_dir(self) -> str:
        raw = self.get("project.input_dir", "./input")
        return os.path.abspath(os.path.expanduser(raw))

    @property
    def output_dir(self) -> str:
        raw = self.get("project.output_dir", "./output")
        return os.path.abspath(os.path.expanduser(raw))

    @property
    def projects_dir(self) -> str:
        raw = self.get("project.projects_dir", "./projects")
        return os.path.abspath(os.path.expanduser(raw))

    @property
    def temp_dir(self) -> str:
        raw = self.get("project.temp_dir", "./temp")
        return os.path.abspath(os.path.expanduser(raw))

    @property
    def min_disk_free_gb(self) -> float:
        return float(self.get("processing.min_disk_free_gb", 5.0))
