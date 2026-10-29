"""Script Review, Editing, Pronunciation Management, and Version Approval Manager."""

import os
import time
import hashlib
from typing import Dict, Any, List, Optional, Tuple

from app.core.logger import get_logger
from app.core.models import ScriptVersion, NarrationSegment, DeliveryProfile
from app.utils.files import safe_write_json, safe_read_json
from app.ai.provider import AIProvider

logger = get_logger()


class ScriptReviewManager:
    """Manages interactive script inspection, per-segment edits, pronunciation rules, and approval gating."""

    def __init__(self, scripts_dir: str):
        self.scripts_dir = os.path.abspath(scripts_dir)
        os.makedirs(self.scripts_dir, exist_ok=True)

    def load_script_version(self, manifest_path: str) -> ScriptVersion:
        """Load script manifest into a typed ScriptVersion model."""
        data = safe_read_json(manifest_path)
        script_ver = ScriptVersion.from_dict(data)
        if not script_ver.content_hash:
            script_ver.content_hash = script_ver.calculate_content_hash()
        return script_ver

    def save_script_version(self, script_version: ScriptVersion, manifest_path: str) -> None:
        """Persist script version and write clean & direction text scripts."""
        script_version.updated_at = time.time()
        script_version.content_hash = script_version.calculate_content_hash()
        safe_write_json(manifest_path, script_version.to_dict())

        # Write clean narration script (only spoken words, ready for TTS)
        clean_txt_path = os.path.join(self.scripts_dir, f"script_{script_version.language}_clean.txt")
        clean_lines = [seg.clean_text or seg.narration_text for seg in script_version.segments]
        with open(clean_txt_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(clean_lines))

        # Write voice direction script (with emotion, delivery notes, and source timestamps)
        direction_txt_path = os.path.join(self.scripts_dir, f"script_{script_version.language}_direction.txt")
        dir_lines = []
        for seg in script_version.segments:
            dir_lines.append(
                f"[{seg.act.upper()}] (Time: {seg.source_time_reference} | Emotion: {seg.emotion} | Pace: {seg.pacing:.2f}x)\n"
                f"Direction: {seg.delivery_notes or 'Conversational natural delivery'}\n"
                f"Pronunciation: {seg.pronunciation_notes or 'Standard'}\n"
                f"Spoken: {seg.narration_text}\n"
            )
        with open(direction_txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(dir_lines))

    def edit_segment(
        self,
        script_version: ScriptVersion,
        segment_id: int,
        new_text: str,
        new_emotion: Optional[str] = None,
        new_pacing: Optional[float] = None
    ) -> bool:
        """Update an individual segment and invalidate previous approval."""
        target_seg = None
        for seg in script_version.segments:
            if seg.segment_id == segment_id:
                target_seg = seg
                break

        if not target_seg:
            logger.warning(f"Segment ID {segment_id} not found in script version.")
            return False

        target_seg.narration_text = new_text.strip()
        target_seg.clean_text = new_text.strip()
        if new_emotion:
            target_seg.emotion = new_emotion
            prof = DeliveryProfile.get_profile(new_emotion)
            target_seg.pacing = prof["pacing"]
        if new_pacing is not None:
            target_seg.pacing = new_pacing

        # Invalidate previous approval because script content changed
        self.invalidate_approval(script_version)
        logger.info(f"Segment #{segment_id} edited. Approval invalidated.")
        return True

    def regenerate_segment_text(
        self,
        script_version: ScriptVersion,
        segment_id: int,
        ai_provider: AIProvider,
        instructions: Optional[str] = None
    ) -> Optional[str]:
        """Regenerate a specific segment's narration using AI Provider."""
        target_seg = None
        for seg in script_version.segments:
            if seg.segment_id == segment_id:
                target_seg = seg
                break

        if not target_seg:
            return None

        prompt = (
            f"You are a professional movie recap scriptwriter. Rewrite this narration segment in {script_version.language.upper()}.\n"
            f"Current Text: \"{target_seg.narration_text}\"\n"
            f"Scene Act: {target_seg.act}\n"
            f"Emotion: {target_seg.emotion}\n"
            f"Guidance: {instructions or 'Make it punchier, conversational, with natural human flow.'}\n"
            f"Return ONLY the rewritten spoken text with no quotes, tags, or introductions."
        )

        try:
            new_text = ai_provider.generate_text(prompt).strip()
            if new_text:
                self.edit_segment(script_version, segment_id, new_text)
                return new_text
        except Exception as exc:
            logger.warning(f"Segment regeneration failed: {exc}")

        return None

    def add_pronunciation_entry(
        self,
        script_version: ScriptVersion,
        word: str,
        phonetic_spelling: str
    ) -> None:
        """Add or update an entry in the pronunciation dictionary."""
        script_version.pronunciation_dictionary[word.strip()] = phonetic_spelling.strip()
        self.invalidate_approval(script_version)
        logger.info(f"Added pronunciation rule: '{word}' -> '{phonetic_spelling}'")

    def approve_script(self, script_version: ScriptVersion) -> str:
        """Explicitly approve the script version, freezing its content hash."""
        script_version.content_hash = script_version.calculate_content_hash()
        script_version.approval_status = "approved"
        script_version.approved_at = time.time()
        if not script_version.script_version_id or script_version.script_version_id == "draft":
            script_version.script_version_id = f"ver_{script_version.content_hash[:8]}_{int(script_version.approved_at)}"
        logger.info(f"Script approved! Version ID: {script_version.script_version_id} (Hash: {script_version.content_hash})")
        return script_version.script_version_id

    def invalidate_approval(self, script_version: ScriptVersion) -> None:
        """Mark script approval as stale/invalidated when edits occur."""
        if script_version.approval_status == "approved":
            script_version.approval_status = "invalidated"
            script_version.approved_at = None
            logger.info("Script approval invalidated due to edits.")

    def is_approved(self, script_version: ScriptVersion) -> bool:
        """Check if script is currently in a valid approved state matching its content hash."""
        if script_version.approval_status != "approved":
            return False
        current_hash = script_version.calculate_content_hash()
        return current_hash == script_version.content_hash
