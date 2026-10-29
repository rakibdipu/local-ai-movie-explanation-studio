import unittest
import os
import shutil
import tempfile
from app.tts.fallback_provider import FallbackTTSProvider
from app.editing.clip_selector import (
    select_supporting_clips_for_segment,
    find_best_source_window_for_segment
)
from app.editing.timeline import build_explanation_timeline
from app.editing.subtitles import generate_explanation_subtitles


class TestTTSAndTimeline(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.fallback_tts = FallbackTTSProvider()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fallback_tts_synthesis(self):
        out_wav = os.path.join(self.temp_dir, "test_audio.wav")
        res = self.fallback_tts.synthesize_to_file(
            text="This is a test explanation sentence.",
            output_file_path=out_wav,
            language="en"
        )
        self.assertTrue(os.path.isfile(out_wav))
        self.assertTrue(os.path.getsize(out_wav) > 100)

    def test_clip_selector(self):
        segment = {
            "segment_id": 1,
            "actual_duration_seconds": 12.0,
            "source_start_seconds": 100.0,
            "source_end_seconds": 200.0
        }
        scenes = [
            {"scene_id": 1, "start_seconds": 90.0, "end_seconds": 130.0},
            {"scene_id": 2, "start_seconds": 130.0, "end_seconds": 180.0},
        ]
        clips = select_supporting_clips_for_segment(segment, scenes, total_movie_duration=600.0)
        total_clip_dur = sum(c["duration"] for c in clips)
        self.assertAlmostEqual(total_clip_dur, 12.0, delta=0.5)

    def test_timeline_and_subtitles(self):
        voice_manifest = {
            "language": "en",
            "segments": [
                {
                    "segment_id": 1,
                    "act": "hook",
                    "narration_text": "In a dark alley, a detective makes a shocking discovery.",
                    "actual_duration_seconds": 6.0,
                    "audio_file": "dummy.wav",
                    "source_start_seconds": 0.0,
                    "source_end_seconds": 60.0
                }
            ]
        }
        scenes = [{"scene_id": 1, "start_seconds": 0.0, "end_seconds": 30.0}]
        timeline_path = os.path.join(self.temp_dir, "timeline.json")
        t_data = build_explanation_timeline(voice_manifest, scenes, total_movie_duration=300.0, output_path=timeline_path)

        self.assertEqual(t_data["total_segments"], 1)
        self.assertTrue(os.path.isfile(timeline_path))

        srt_path = os.path.join(self.temp_dir, "final.srt")
        ass_path = os.path.join(self.temp_dir, "final.ass")
        generate_explanation_subtitles(t_data, srt_path, ass_path)

        self.assertTrue(os.path.isfile(srt_path))
        self.assertTrue(os.path.isfile(ass_path))

    def test_semantic_scene_matching(self):
        """Verify that narration mentioning specific characters and events matches relevant movie chunk."""
        chunks = [
            {
                "chunk_id": 1,
                "start_seconds": 0.0,
                "end_seconds": 300.0,
                "summary": "Introduction to the quiet harbor life and fishing boats.",
                "characters": ["Elderly Fisherman"],
                "events": ["Boat departs"]
            },
            {
                "chunk_id": 2,
                "start_seconds": 300.0,
                "end_seconds": 600.0,
                "summary": "Police officer Harris raids the illegal gold warehouse and corners Amir.",
                "characters": ["Harris", "Amir"],
                "events": ["Police raid", "Gold seized", "Amir escapes"]
            },
            {
                "chunk_id": 3,
                "start_seconds": 600.0,
                "end_seconds": 900.0,
                "summary": "Hospital scene where family gathers in grief.",
                "characters": ["Fiza", "Doctor"],
                "events": ["Emergency care"]
            }
        ]

        segment = {
            "segment_id": 2,
            "act": "inciting_incident",
            "narration_text": "Officer Harris led a sudden raid on the warehouse, catching Amir by surprise.",
            "clean_text": "Officer Harris led a sudden raid on the warehouse, catching Amir by surprise.",
            "source_start_seconds": 0.0,
            "source_end_seconds": 300.0,
            "actual_duration_seconds": 15.0
        }

        matched_start, matched_end = find_best_source_window_for_segment(
            segment=segment,
            chunk_analyses=chunks,
            total_movie_duration=900.0,
            fallback_start=0.0,
            fallback_end=300.0
        )

        # Must match Chunk 2 (300.0s - 600.0s) because Harris and Amir are both in it
        self.assertEqual(matched_start, 300.0)
        self.assertEqual(matched_end, 600.0)

    def test_zero_cumulative_drift_across_segments(self):
        """Verify that visual clip durations exactly match fractional voiceover lengths with zero drift."""
        voice_manifest = {
            "language": "en",
            "total_duration_seconds": 34.63,
            "segments": [
                {
                    "segment_id": 1,
                    "act": "hook",
                    "narration_text": "First hook segment narration.",
                    "actual_duration_seconds": 11.37,
                    "source_start_seconds": 0.0,
                    "source_end_seconds": 100.0
                },
                {
                    "segment_id": 2,
                    "act": "escalation",
                    "narration_text": "Tense confrontation begins.",
                    "actual_duration_seconds": 14.82,
                    "source_start_seconds": 100.0,
                    "source_end_seconds": 250.0
                },
                {
                    "segment_id": 3,
                    "act": "climax",
                    "narration_text": "Final battle ends.",
                    "actual_duration_seconds": 8.44,
                    "source_start_seconds": 250.0,
                    "source_end_seconds": 400.0
                }
            ]
        }
        scenes = [
            {"scene_id": 1, "start_seconds": 0.0, "end_seconds": 80.0},
            {"scene_id": 2, "start_seconds": 80.0, "end_seconds": 200.0},
            {"scene_id": 3, "start_seconds": 200.0, "end_seconds": 400.0}
        ]
        timeline_path = os.path.join(self.temp_dir, "drift_timeline.json")
        t_data = build_explanation_timeline(
            voice_manifest=voice_manifest,
            scenes=scenes,
            total_movie_duration=400.0,
            output_path=timeline_path
        )

        self.assertTrue(t_data["sync_verified"])
        self.assertLess(t_data["av_sync_max_drift_seconds"], 0.05)

        for it in t_data["items"]:
            # Segment audio duration must equal clips total duration
            self.assertAlmostEqual(it["duration_seconds"], it["clips_total_duration_seconds"], places=2)

    def test_emotion_aware_cutting_rhythm(self):
        """Verify that action/climax scenes cut faster (more clips) than slow suspense scenes."""
        scenes = [{"scene_id": 1, "start_seconds": 0.0, "end_seconds": 300.0}]

        action_seg = {
            "segment_id": 1,
            "actual_duration_seconds": 18.0,
            "emotion": "action",
            "source_start_seconds": 50.0,
            "source_end_seconds": 150.0
        }
        suspense_seg = {
            "segment_id": 2,
            "actual_duration_seconds": 18.0,
            "emotion": "suspense",
            "source_start_seconds": 50.0,
            "source_end_seconds": 150.0
        }

        action_clips = select_supporting_clips_for_segment(action_seg, scenes, total_movie_duration=300.0)
        suspense_clips = select_supporting_clips_for_segment(suspense_seg, scenes, total_movie_duration=300.0)

        # Action should have more frequent cuts (more clips) than suspense
        self.assertGreater(len(action_clips), len(suspense_clips))


if __name__ == "__main__":
    unittest.main()
