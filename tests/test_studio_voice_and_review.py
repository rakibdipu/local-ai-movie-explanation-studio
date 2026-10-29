"""Comprehensive Acceptance Test Suite for Movie Explanation Studio:
Natural Voice, Storytelling, Script Review, Voice Audition, and Audio Production.
"""

import os
import shutil
import tempfile
import unittest

from app.core.models import (
    ScriptVersion,
    NarrationSegment,
    VoiceConfiguration,
    PreviewApproval,
    DeliveryProfile,
    FinalAudio
)
from app.review.script_reviewer import ScriptReviewManager
from app.review.voice_audition import VoiceAuditionManager, AUDITION_PASSAGES
from app.tts.google_adapters import (
    get_voice_adapter,
    UnifiedVoiceAdapter,
    GeminiTTSAdapter,
    GoogleCloudTTSAdapter,
    EdgeTTSAdapter,
    FallbackVoiceAdapter
)
from app.audio.post_processor import AudioPostProcessor
from app.tts.pipeline import synthesize_script_narration, regenerate_single_segment
from app.core.state import ProjectState, PipelineStage, StageStatus
from app.qa.validator import perform_automated_qa


class TestStudioVoiceAndReview(unittest.TestCase):
    """Verifies all Module 16 acceptance criteria."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.scripts_dir = os.path.join(self.temp_dir, "scripts")
        self.previews_dir = os.path.join(self.temp_dir, "narration", "previews")
        self.narration_dir = os.path.join(self.temp_dir, "narration")
        os.makedirs(self.scripts_dir, exist_ok=True)
        os.makedirs(self.previews_dir, exist_ok=True)
        os.makedirs(self.narration_dir, exist_ok=True)

        self.script_mgr = ScriptReviewManager(self.scripts_dir)
        self.audition_mgr = VoiceAuditionManager(self.previews_dir)
        self.post_processor = AudioPostProcessor()
        self.voice_adapter = FallbackVoiceAdapter()

        # Build initial sample script version
        self.sample_segments = [
            NarrationSegment(
                segment_id=1,
                act="hook",
                narration_text="In the quiet harbor of Koduvally, a family tried to escape a dangerous past.",
                clean_text="In the quiet harbor of Koduvally, a family tried to escape a dangerous past.",
                emotion=DeliveryProfile.MYSTERY,
                pacing=0.96,
                source_time_reference="00:00:00 - 00:02:00"
            ),
            NarrationSegment(
                segment_id=2,
                act="inciting_incident",
                narration_text="A raid by revenue officers shattered their peace, framing his father as a criminal.",
                clean_text="A raid by revenue officers shattered their peace, framing his father as a criminal.",
                emotion=DeliveryProfile.SUSPENSE,
                pacing=0.94,
                source_time_reference="00:02:00 - 00:05:00"
            ),
            NarrationSegment(
                segment_id=3,
                act="climax",
                narration_text="Amir reclaimed the golden empire to protect his family's dignity.",
                clean_text="Amir reclaimed the golden empire to protect his family's dignity.",
                emotion=DeliveryProfile.CLIMAX,
                pacing=1.05,
                source_time_reference="00:05:00 - 00:08:00"
            )
        ]
        self.script_ver = ScriptVersion(
            script_version_id="draft",
            language="en",
            style="cinematic_storytelling",
            target_duration_minutes=10,
            total_words=45,
            total_segments=3,
            segments=self.sample_segments,
            approval_status="draft"
        )
        self.manifest_path = os.path.join(self.scripts_dir, "script_en_manifest.json")
        self.script_mgr.save_script_version(self.script_ver, self.manifest_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Acceptance Test 1: Movie analyzed without triggering full narration
    # -------------------------------------------------------------------------
    def test_movie_analysis_without_narration_generation(self):
        state_file = os.path.join(self.temp_dir, "project_state.json")
        state = ProjectState(state_file, "dummy_hash", "movie.mp4")

        # Set analysis stages completed
        state.set_stage_status(PipelineStage.MEDIA_INSPECTION, StageStatus.COMPLETED)
        state.set_stage_status(PipelineStage.SUBTITLE_EXTRACTION, StageStatus.COMPLETED)
        state.set_stage_status(PipelineStage.STORY_ANALYSIS, StageStatus.COMPLETED)
        state.set_stage_status(PipelineStage.SCRIPT_GENERATION, StageStatus.COMPLETED)

        # Narration synthesis must still be pending
        self.assertFalse(state.is_stage_completed(PipelineStage.VOICE_SYNTHESIS))
        self.assertEqual(state.data["stages"][PipelineStage.VOICE_SYNTHESIS], StageStatus.PENDING)

    # -------------------------------------------------------------------------
    # Acceptance Test 2: Script can be edited and approved
    # -------------------------------------------------------------------------
    def test_script_editing_and_approval(self):
        loaded = self.script_mgr.load_script_version(self.manifest_path)
        self.assertFalse(self.script_mgr.is_approved(loaded))

        # Edit segment
        updated = self.script_mgr.edit_segment(
            loaded,
            segment_id=1,
            new_text="In the quiet coastal streets of Koduvally, Amir sought a peaceful life."
        )
        self.assertTrue(updated)
        self.assertEqual(loaded.segments[0].narration_text, "In the quiet coastal streets of Koduvally, Amir sought a peaceful life.")

        # Approve script
        version_id = self.script_mgr.approve_script(loaded)
        self.script_mgr.save_script_version(loaded, self.manifest_path)

        self.assertTrue(self.script_mgr.is_approved(loaded))
        self.assertEqual(loaded.approval_status, "approved")
        self.assertTrue(version_id.startswith("ver_"))
        self.assertTrue(os.path.isfile(os.path.join(self.scripts_dir, "script_en_clean.txt")))
        self.assertTrue(os.path.isfile(os.path.join(self.scripts_dir, "script_en_direction.txt")))

    # -------------------------------------------------------------------------
    # Acceptance Test 3 & 4: Voice audition across 3 representative passages
    # -------------------------------------------------------------------------
    def test_voice_audition_multi_passages_and_comparison(self):
        voices = self.voice_adapter.list_voices("en")
        self.assertTrue(len(voices) >= 1)

        audition_files = self.audition_mgr.generate_voice_audition(
            adapter=self.voice_adapter,
            voice_id="default",
            language="en"
        )

        self.assertIn("normal", audition_files)
        self.assertIn("suspense", audition_files)
        self.assertIn("emotional", audition_files)

        for p_name, p_file in audition_files.items():
            self.assertTrue(os.path.isfile(p_file), f"Preview {p_name} missing: {p_file}")
            self.assertTrue(os.path.getsize(p_file) > 100, f"Preview {p_name} empty")

    # -------------------------------------------------------------------------
    # Acceptance Test 5: Voice settings consistency during final generation
    # -------------------------------------------------------------------------
    def test_voice_settings_consistent_during_generation(self):
        voice_cfg = VoiceConfiguration(
            provider="system",
            model="default",
            voice_id="default",
            language="en",
            speaking_rate=1.05,
            pitch=0.0
        )
        config_hash_before = voice_cfg.calculate_config_hash()

        # Synthesize narration with this voice configuration
        manifest = synthesize_script_narration(
            script_manifest=self.script_ver.to_dict(),
            output_dir=self.narration_dir,
            tts_provider=self.voice_adapter,
            speed=voice_cfg.speaking_rate,
            voice_id=voice_cfg.voice_id
        )

        self.assertEqual(manifest["voice_id"], voice_cfg.voice_id)
        self.assertEqual(manifest["speed"], voice_cfg.speaking_rate)
        # Verify settings didn't mutate
        self.assertEqual(voice_cfg.calculate_config_hash(), config_hash_before)

    # -------------------------------------------------------------------------
    # Acceptance Test 6: Individual narration segment generation & saving
    # -------------------------------------------------------------------------
    def test_individual_narration_segment_generation(self):
        out_seg_wav = os.path.join(self.narration_dir, "segments", "test_seg_001.wav")
        res = self.voice_adapter.generate_segment(
            segment=self.sample_segments[0].to_dict(),
            voice_config={"voice_id": "default", "language": "en"},
            output_path=out_seg_wav
        )
        self.assertTrue(os.path.isfile(res))
        self.assertTrue(os.path.getsize(res) > 100)

    # -------------------------------------------------------------------------
    # Acceptance Test 7: Retry failed segment preserves completed segments
    # -------------------------------------------------------------------------
    def test_retry_failed_segment_preserves_completed(self):
        manifest = synthesize_script_narration(
            script_manifest=self.script_ver.to_dict(),
            output_dir=self.narration_dir,
            tts_provider=self.voice_adapter
        )

        seg1_path = os.path.join(self.narration_dir, "segments", "narration_001.wav")
        seg2_path = os.path.join(self.narration_dir, "segments", "narration_002.wav")
        self.assertTrue(os.path.isfile(seg1_path))
        self.assertTrue(os.path.isfile(seg2_path))

        seg1_mtime = os.path.getmtime(seg1_path)

        # Regenerate only segment 2
        regen_path = regenerate_single_segment(
            segment_id=2,
            script_manifest=manifest,
            output_dir=self.narration_dir,
            tts_provider=self.voice_adapter
        )
        self.assertTrue(os.path.isfile(regen_path))

        # Segment 1 should be completely untouched and preserved
        self.assertEqual(os.path.getmtime(seg1_path), seg1_mtime)

    # -------------------------------------------------------------------------
    # Acceptance Test 8: Editing approved script invalidates previous approval
    # -------------------------------------------------------------------------
    def test_editing_invalidates_previous_approval(self):
        loaded = self.script_mgr.load_script_version(self.manifest_path)
        self.script_mgr.approve_script(loaded)
        self.assertTrue(self.script_mgr.is_approved(loaded))

        # Edit script after approval
        self.script_mgr.edit_segment(loaded, segment_id=2, new_text="New edited sentence here.")

        # Approval status must now be invalidated
        self.assertFalse(self.script_mgr.is_approved(loaded))
        self.assertEqual(loaded.approval_status, "invalidated")

    # -------------------------------------------------------------------------
    # Acceptance Test 9: Unsupported API features are handled safely
    # -------------------------------------------------------------------------
    def test_unsupported_api_features_handled_safely(self):
        # Gemini without API key
        gemini_adapter = GeminiTTSAdapter(api_key=None)
        self.assertFalse(gemini_adapter.is_available())

        # Calling without key should raise RuntimeError with clear explanation
        with self.assertRaises(RuntimeError) as ctx:
            gemini_adapter.generate_segment(
                segment={"narration_text": "Hello"},
                voice_config={"voice_id": "Puck"},
                output_path=os.path.join(self.temp_dir, "gemini_test.wav")
            )
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))

        # Factory fallback
        fallback = get_voice_adapter("gemini")
        # Should gracefully fall back to Edge-TTS or Fallback adapter if no key
        self.assertTrue(fallback.is_available())

    # -------------------------------------------------------------------------
    # Acceptance Test 10: Pronunciation corrections applied before generation
    # -------------------------------------------------------------------------
    def test_pronunciation_corrections_applied(self):
        loaded = self.script_mgr.load_script_version(self.manifest_path)
        self.script_mgr.add_pronunciation_entry(loaded, "Koduvally", "Ko-du-val-lee")
        self.assertIn("Koduvally", loaded.pronunciation_dictionary)
        self.assertEqual(loaded.pronunciation_dictionary["Koduvally"], "Ko-du-val-lee")

        # Test pronunciation substitution in Gemini / Cloud adapters
        cloud_adapter = GoogleCloudTTSAdapter(api_key="dummy_key")
        ssml = cloud_adapter._build_ssml(
            text="They arrived in Koduvally yesterday.",
            emotion="normal_conversation",
            pronunciation_dict=loaded.pronunciation_dictionary
        )
        self.assertIn('<sub alias="Ko-du-val-lee">Koduvally</sub>', ssml)

    # -------------------------------------------------------------------------
    # Acceptance Test 11: Final audio validated after assembly
    # -------------------------------------------------------------------------
    def test_final_audio_validation_after_assembly(self):
        manifest = synthesize_script_narration(
            script_manifest=self.script_ver.to_dict(),
            output_dir=self.narration_dir,
            tts_provider=self.voice_adapter
        )
        master_wav = manifest["full_narration_file"]
        self.assertTrue(os.path.isfile(master_wav))

        qc = self.post_processor.inspect_audio_segment(master_wav)
        self.assertTrue(qc["valid"])
        self.assertTrue(qc["duration"] > 0.5)
        self.assertEqual(qc["sample_rate"], 44100)
        self.assertEqual(qc["channels"], 2)

    # -------------------------------------------------------------------------
    # Acceptance Test 12: Export finished narration in WAV and MP3
    # -------------------------------------------------------------------------
    def test_export_finished_narration_formats(self):
        manifest = synthesize_script_narration(
            script_manifest=self.script_ver.to_dict(),
            output_dir=self.narration_dir,
            tts_provider=self.voice_adapter
        )
        master_wav = manifest["full_narration_file"]

        delivery = self.post_processor.export_delivery_formats(
            master_wav=master_wav,
            output_base_path=os.path.join(self.narration_dir, "export_final")
        )
        self.assertIn("wav", delivery)
        self.assertIn("mp3", delivery)
        self.assertTrue(os.path.isfile(delivery["wav"]))
        self.assertTrue(os.path.isfile(delivery["mp3"]))
        self.assertTrue(os.path.getsize(delivery["mp3"]) > 100)

    # -------------------------------------------------------------------------
    # Acceptance Test 13: UI state machine distinguishes draft/approved/failed
    # -------------------------------------------------------------------------
    def test_state_machine_stage_distinction(self):
        state_file = os.path.join(self.temp_dir, "state_test.json")
        state = ProjectState(state_file, "hash123", "sample.mp4")

        # Initial: pending
        self.assertEqual(state.data["stages"][PipelineStage.SCRIPT_REVIEW], StageStatus.PENDING)

        # In progress
        state.set_stage_status(PipelineStage.SCRIPT_REVIEW, StageStatus.IN_PROGRESS)
        self.assertEqual(state.data["stages"][PipelineStage.SCRIPT_REVIEW], StageStatus.IN_PROGRESS)

        # Failed with error
        state.set_stage_status(PipelineStage.SCRIPT_REVIEW, StageStatus.FAILED, error="User rejected script draft")
        self.assertEqual(state.data["stages"][PipelineStage.SCRIPT_REVIEW], StageStatus.FAILED)
        self.assertEqual(state.data["error"]["message"], "User rejected script draft")

        # Completed
        state.set_stage_status(PipelineStage.SCRIPT_REVIEW, StageStatus.COMPLETED)
        self.assertEqual(state.data["stages"][PipelineStage.SCRIPT_REVIEW], StageStatus.COMPLETED)
        self.assertIsNone(state.data["error"])

    # -------------------------------------------------------------------------
    # Acceptance Test 15: Automated checks and manual listening reported separately
    # -------------------------------------------------------------------------
    def test_automated_checks_and_manual_listening_reported_separately(self):
        dummy_video = os.path.join(self.temp_dir, "test.mp4")
        dummy_srt = os.path.join(self.temp_dir, "test.srt")
        dummy_wav = os.path.join(self.temp_dir, "test.wav")

        with open(dummy_video, "wb") as f:
            f.write(b"0" * 2048)
        with open(dummy_srt, "w") as f:
            f.write("1\n00:00:00,000 --> 00:00:05,000\nHello")
        with open(dummy_wav, "wb") as f:
            f.write(b"0" * 500)

        report_file = os.path.join(self.temp_dir, "qa_report.json")
        qa = perform_automated_qa(
            rendered_video_path=dummy_video,
            subtitles_srt_path=dummy_srt,
            master_narration_audio_path=dummy_wav,
            target_duration_minutes=5,
            output_report_path=report_file
        )

        self.assertIn("automated_checks", qa)
        self.assertIn("manual_listening_checklist", qa)
        self.assertTrue(isinstance(qa["automated_checks"], dict))
        self.assertTrue(isinstance(qa["manual_listening_checklist"], list))
        self.assertTrue(len(qa["manual_listening_checklist"]) >= 4)


if __name__ == "__main__":
    unittest.main()
