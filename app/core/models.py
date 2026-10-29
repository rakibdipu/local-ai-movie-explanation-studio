"""Data models for Script Versions, Narration Segments, Voice Config, and Audio Approvals."""

import os
import time
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional


class DeliveryProfile:
    """Creative delivery profiles for natural, emotion-aware movie narration."""
    NORMAL_CONVERSATION = "normal_conversation"
    MYSTERY = "mystery"
    SUSPENSE = "suspense"
    ACTION = "action"
    SADNESS = "sadness"
    EMOTIONAL_REVELATION = "emotional_revelation"
    COMEDY = "comedy"
    HORROR = "horror"
    CLIMAX = "climax"
    RESOLUTION = "resolution"

    ALL_PROFILES = [
        NORMAL_CONVERSATION,
        MYSTERY,
        SUSPENSE,
        ACTION,
        SADNESS,
        EMOTIONAL_REVELATION,
        COMEDY,
        HORROR,
        CLIMAX,
        RESOLUTION
    ]

    PROPERTIES = {
        NORMAL_CONVERSATION: {
            "pacing": 1.0,
            "pitch": 0,
            "description": "Warm, clear, relaxed, naturally expressive, and moderately paced.",
            "guidelines": "Conversational storytelling with an interested friend."
        },
        MYSTERY: {
            "pacing": 0.96,
            "pitch": -1,
            "description": "Curious and controlled, subtle emphasis on clues.",
            "guidelines": "Controlled tone, slight pause before revealing details."
        },
        SUSPENSE: {
            "pacing": 0.94,
            "pitch": -2,
            "description": "Measured pacing, restrained intensity, strategic pauses.",
            "guidelines": "Allow tension to build without artificial breathiness."
        },
        ACTION: {
            "pacing": 1.06,
            "pitch": +1,
            "description": "Energetic, direct, concise, slightly faster delivery.",
            "guidelines": "Fast-paced without sacrificing clear pronunciation."
        },
        SADNESS: {
            "pacing": 0.92,
            "pitch": -2,
            "description": "Gentle, sincere, slower delivery without melodrama.",
            "guidelines": "Let emotional weight land naturally."
        },
        EMOTIONAL_REVELATION: {
            "pacing": 0.95,
            "pitch": 0,
            "description": "Intimate, clear, reflective, space to land.",
            "guidelines": "Significant revelations given deliberate timing."
        },
        COMEDY: {
            "pacing": 1.03,
            "pitch": +1,
            "description": "Conversational timing and space for humor to work.",
            "guidelines": "Natural dry or playful delivery, never forced."
        },
        HORROR: {
            "pacing": 0.93,
            "pitch": -2,
            "description": "Controlled tension, deliberate pacing, quiet emphasis.",
            "guidelines": "Subtle dread instead of constant screaming."
        },
        CLIMAX: {
            "pacing": 1.05,
            "pitch": +2,
            "description": "Increasing intensity and peak emotional stakes.",
            "guidelines": "Build excitement only where justified by the scene."
        },
        RESOLUTION: {
            "pacing": 0.97,
            "pitch": 0,
            "description": "Calm, warm, reflective, allowing the story to settle.",
            "guidelines": "Closure and thoughtful conclusion."
        }
    }

    @classmethod
    def get_profile(cls, name: str) -> Dict[str, Any]:
        key = name.lower().replace(" ", "_")
        return cls.PROPERTIES.get(key, cls.PROPERTIES[cls.NORMAL_CONVERSATION])


@dataclass
class NarrationSegment:
    """Individual chunk of speech narration synchronized with movie scenes."""
    segment_id: int
    act: str = "scene"
    narration_text: str = ""
    clean_text: str = ""
    emotion: str = DeliveryProfile.NORMAL_CONVERSATION
    pacing: float = 1.0
    delivery_notes: str = ""
    pronunciation_notes: str = ""
    pause_instructions: str = ""
    source_start_seconds: float = 0.0
    source_end_seconds: float = 0.0
    source_time_reference: str = "00:00:00 - 00:00:00"
    estimated_seconds: float = 15.0
    actual_duration_seconds: float = 0.0
    audio_status: str = "pending"  # pending, synthesizing, completed, failed
    audio_file: Optional[str] = None
    script_version_id: str = ""
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NarrationSegment":
        clean = data.get("clean_text") or data.get("narration_text", "")
        return cls(
            segment_id=data.get("segment_id", 1),
            act=data.get("act", "scene"),
            narration_text=data.get("narration_text", ""),
            clean_text=clean,
            emotion=data.get("emotion", DeliveryProfile.NORMAL_CONVERSATION),
            pacing=float(data.get("pacing", 1.0)),
            delivery_notes=data.get("delivery_notes", ""),
            pronunciation_notes=data.get("pronunciation_notes", ""),
            pause_instructions=data.get("pause_instructions", ""),
            source_start_seconds=float(data.get("source_start_seconds", 0.0)),
            source_end_seconds=float(data.get("source_end_seconds", 0.0)),
            source_time_reference=data.get("source_time_reference", "00:00:00 - 00:00:00"),
            estimated_seconds=float(data.get("estimated_seconds", 15.0)),
            actual_duration_seconds=float(data.get("actual_duration_seconds", 0.0)),
            audio_status=data.get("audio_status", "pending"),
            audio_file=data.get("audio_file"),
            script_version_id=data.get("script_version_id", ""),
            error_message=data.get("error_message")
        )


@dataclass
class ScriptVersion:
    """Versioned script manifest with approval tracking and pronunciation dictionary."""
    script_version_id: str
    language: str
    style: str
    target_duration_minutes: int
    total_words: int
    total_segments: int
    segments: List[NarrationSegment] = field(default_factory=list)
    approval_status: str = "draft"  # draft, approved, invalidated, stale
    approved_at: Optional[float] = None
    content_hash: str = ""
    pronunciation_dictionary: Dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def calculate_content_hash(self) -> str:
        """Calculate SHA-256 fingerprint of the spoken text and segment order."""
        hasher = hashlib.sha256()
        for seg in self.segments:
            hasher.update(str(seg.segment_id).encode("utf-8"))
            hasher.update(seg.narration_text.strip().encode("utf-8"))
            hasher.update(seg.emotion.encode("utf-8"))
        return hasher.hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["segments"] = [s.to_dict() if isinstance(s, NarrationSegment) else s for s in self.segments]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScriptVersion":
        raw_segs = data.get("segments", [])
        segments = [
            NarrationSegment.from_dict(s) if isinstance(s, dict) else s
            for s in raw_segs
        ]
        return cls(
            script_version_id=data.get("script_version_id", ""),
            language=data.get("language", "en"),
            style=data.get("style", "cinematic_storytelling"),
            target_duration_minutes=int(data.get("target_duration_minutes", 20)),
            total_words=int(data.get("total_words", 0)),
            total_segments=int(data.get("total_segments", len(segments))),
            segments=segments,
            approval_status=data.get("approval_status", "draft"),
            approved_at=data.get("approved_at"),
            content_hash=data.get("content_hash", ""),
            pronunciation_dictionary=data.get("pronunciation_dictionary", {}),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time()))
        )


@dataclass
class VoiceConfiguration:
    """Narrator voice selection and provider-specific configuration."""
    provider: str  # gemini, google_cloud, edge-tts, system
    model: str
    voice_id: str
    language: str
    locale: str = "en-US"
    speaking_rate: float = 1.0
    pitch: float = 0.0
    volume_gain_db: float = 0.0
    supported_settings: Dict[str, Any] = field(default_factory=dict)
    selected_at: float = field(default_factory=time.time)

    def calculate_config_hash(self) -> str:
        hasher = hashlib.sha256()
        raw = f"{self.provider}:{self.voice_id}:{self.speaking_rate}:{self.pitch}:{self.language}"
        hasher.update(raw.encode("utf-8"))
        return hasher.hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoiceConfiguration":
        return cls(
            provider=data.get("provider", "edge-tts"),
            model=data.get("model", "default"),
            voice_id=data.get("voice_id", "default"),
            language=data.get("language", "en"),
            locale=data.get("locale", "en-US"),
            speaking_rate=float(data.get("speaking_rate", 1.0)),
            pitch=float(data.get("pitch", 0.0)),
            volume_gain_db=float(data.get("volume_gain_db", 0.0)),
            supported_settings=data.get("supported_settings", {}),
            selected_at=float(data.get("selected_at", time.time()))
        )


@dataclass
class PreviewApproval:
    """Approval record for auditioned voice preview."""
    script_version_id: str
    voice_config_hash: str
    voice_id: str
    preview_asset_references: Dict[str, str] = field(default_factory=dict)  # normal, suspense, emotional
    approval_status: str = "pending"  # pending, approved, rejected, stale
    approved_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PreviewApproval":
        return cls(
            script_version_id=data.get("script_version_id", ""),
            voice_config_hash=data.get("voice_config_hash", ""),
            voice_id=data.get("voice_id", ""),
            preview_asset_references=data.get("preview_asset_references", {}),
            approval_status=data.get("approval_status", "pending"),
            approved_at=data.get("approved_at")
        )


@dataclass
class FinalAudio:
    """Final assembled and post-processed narration audio asset."""
    audio_asset_reference: str
    format: str = "wav"
    sample_rate: int = 44100
    channel_count: int = 2
    total_duration_seconds: float = 0.0
    quality_check_status: str = "pending"  # passed, warning, failed
    quality_report: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FinalAudio":
        return cls(
            audio_asset_reference=data.get("audio_asset_reference", ""),
            format=data.get("format", "wav"),
            sample_rate=int(data.get("sample_rate", 44100)),
            channel_count=int(data.get("channel_count", 2)),
            total_duration_seconds=float(data.get("total_duration_seconds", 0.0)),
            quality_check_status=data.get("quality_check_status", "pending"),
            quality_report=data.get("quality_report", {})
        )
