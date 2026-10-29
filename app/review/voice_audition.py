"""Voice Selection, Multi-Passage Audition, and Preview Approval Manager."""

import os
import time
from typing import Dict, Any, List, Optional

from app.core.logger import get_logger
from app.core.models import VoiceConfiguration, PreviewApproval, DeliveryProfile
from app.tts.google_adapters import UnifiedVoiceAdapter, get_voice_adapter
from app.utils.files import safe_write_json, safe_read_json

logger = get_logger()

# 3 Representative audition passages per language matching Module 9 specifications
AUDITION_PASSAGES = {
    "en": {
        "normal": "In a quiet coastal town, an ordinary family thought they had left the dangerous past behind them. But destiny had other plans.",
        "suspense": "Late at night, a mysterious unmarked ship docked in the fog-covered harbor. Deep in the shadows, armed men waited in dead silence.",
        "emotional": "Looking at his father's worn-out watch, he realized the painful truth. True honor isn't about power—it's about protecting the ones you love."
    },
    "bn": {
        "normal": "দক্ষিণ ভারতের কোডুভাল্লিতে এক সাধারণ পরিবার শান্তির জীবন খুঁজছিল। কিন্তু ভাগ্যের নির্মম পরিহাস তাদের জন্য এক অন্য ইতিহাস লিখে রেখেছিল।",
        "suspense": "গভীর সমুদ্রবন্দরে রাতের কুয়াশার মধ্যে নিঃশব্দে ভেসে ওঠে এক নামহীন জাহাজ। ঘোর অন্ধকারের ভেতর নিঃশ্বাস বন্ধ করে অপেক্ষা করছিল সশস্ত্র প্রহরীরা।",
        "emotional": "বাবার রেখে যাওয়া পুরনো স্মৃতির দিকে তাকিয়ে সে বুঝতে পারল জীবনের সবচেয়ে কঠিন সত্য। আসল সম্মান ক্ষমতায় নয়, বরং পরিবারের আত্মমর্যাদা রক্ষার মাঝে।"
    },
    "hi": {
        "normal": "एक शांत शहर में एक सीधा-साधा परिवार अपनी पुरानी जिंदगी को पीछे छोड़कर नई शुरुआत कर रहा था। लेकिन किस्मत को कुछ और ही मंजूर था।",
        "suspense": "रात के घने कोहरे में एक अज्ञात जहाज धीरे-धीरे बंदरगाह की ओर बढ़ रहा था। अंधेरे के साए में हथियारबंद लोग सांसें थामे खड़े थे।",
        "emotional": "अपने पिता की पुरानी निशानी को देखकर उसे जिंदगी का सबसे बड़ा सच समझ में आया। असली ताकत ताकत दिखाने में नहीं, अपनों के मान-सम्मान को बचाने में है।"
    }
}


class VoiceAuditionManager:
    """Handles narrator auditioning across normal, suspenseful, and emotional passages."""

    def __init__(self, previews_dir: str):
        self.previews_dir = os.path.abspath(previews_dir)
        os.makedirs(self.previews_dir, exist_ok=True)

    def get_audition_passages(self, language: str) -> Dict[str, str]:
        lang = language.lower()
        return AUDITION_PASSAGES.get(lang, AUDITION_PASSAGES["en"])

    def generate_voice_audition(
        self,
        adapter: UnifiedVoiceAdapter,
        voice_id: str,
        language: str,
        pronunciation_dict: Optional[Dict[str, str]] = None,
        pitch: Any = 0
    ) -> Dict[str, str]:
        """Synthesize all 3 audition passages for a specific voice candidate."""
        passages = self.get_audition_passages(language)
        sanitized_voice = voice_id.replace(" ", "_").replace(":", "_")
        voice_preview_dir = os.path.join(self.previews_dir, sanitized_voice)
        os.makedirs(voice_preview_dir, exist_ok=True)

        results = {}
        # 1. Normal passage
        normal_wav = os.path.join(voice_preview_dir, "preview_1_normal.wav")
        adapter.preview_voice(
            voice_id=voice_id,
            sample_text=passages["normal"],
            emotion=DeliveryProfile.NORMAL_CONVERSATION,
            language=language,
            output_file=normal_wav,
            pronunciation_dict=pronunciation_dict,
            pitch=pitch
        )
        results["normal"] = normal_wav

        # 2. Suspenseful passage
        suspense_wav = os.path.join(voice_preview_dir, "preview_2_suspense.wav")
        adapter.preview_voice(
            voice_id=voice_id,
            sample_text=passages["suspense"],
            emotion=DeliveryProfile.SUSPENSE,
            language=language,
            output_file=suspense_wav,
            pronunciation_dict=pronunciation_dict,
            pitch=pitch
        )
        results["suspense"] = suspense_wav

        # 3. Emotional passage
        emotional_wav = os.path.join(voice_preview_dir, "preview_3_emotional.wav")
        adapter.preview_voice(
            voice_id=voice_id,
            sample_text=passages["emotional"],
            emotion=DeliveryProfile.EMOTIONAL_REVELATION,
            language=language,
            output_file=emotional_wav,
            pronunciation_dict=pronunciation_dict,
            pitch=pitch
        )
        results["emotional"] = emotional_wav

        logger.info(f"Generated 3-passage voice audition for '{voice_id}' in {voice_preview_dir}")
        return results

    def approve_voice_preview(
        self,
        script_version_id: str,
        voice_config: VoiceConfiguration,
        preview_files: Dict[str, str],
        approval_file_path: str
    ) -> PreviewApproval:
        """Explicitly record user approval of voice preview before final TTS generation."""
        approval = PreviewApproval(
            script_version_id=script_version_id,
            voice_config_hash=voice_config.calculate_config_hash(),
            voice_id=voice_config.voice_id,
            preview_asset_references=preview_files,
            approval_status="approved",
            approved_at=time.time()
        )
        safe_write_json(approval_file_path, approval.to_dict())
        logger.info(f"Voice preview approved! Voice: {voice_config.voice_id} (Config Hash: {approval.voice_config_hash})")
        return approval

    def load_preview_approval(self, approval_file_path: str) -> Optional[PreviewApproval]:
        if not os.path.isfile(approval_file_path):
            return None
        try:
            data = safe_read_json(approval_file_path)
            return PreviewApproval.from_dict(data)
        except Exception:
            return None

    def is_preview_valid(
        self,
        approval_file_path: str,
        current_script_version_id: str,
        current_voice_config: VoiceConfiguration
    ) -> bool:
        """Verify that current voice preview approval matches active script version and voice configuration."""
        approval = self.load_preview_approval(approval_file_path)
        if not approval or approval.approval_status != "approved":
            return False
        if approval.script_version_id != current_script_version_id:
            logger.info("Voice preview is stale: Script version changed.")
            return False
        if approval.voice_config_hash != current_voice_config.calculate_config_hash():
            logger.info("Voice preview is stale: Voice configuration changed.")
            return False
        return True
