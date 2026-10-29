import unittest
import os
import shutil
import tempfile
from app.thumbnail.generator import generate_thumbnail_concepts, create_thumbnail
from app.qa.validator import perform_automated_qa


class TestQAAndThumbnail(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.dummy_story = {
            "logline": "A thrilling detective story set in an old harbour town.",
            "climax": [{"description": "Roy catches the criminal at midnight."}],
            "setup": [{"description": "Roy arrives in town."}],
            "resolution": [{"description": "Justice is served."}]
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_thumbnail_concepts(self):
        bn_concepts = generate_thumbnail_concepts(self.dummy_story, "bn")
        self.assertEqual(len(bn_concepts), 3)
        self.assertIn("রহস্য", bn_concepts[0]["headline"])

        hi_concepts = generate_thumbnail_concepts(self.dummy_story, "hi")
        self.assertEqual(len(hi_concepts), 3)
        self.assertIn("राज़", hi_concepts[0]["headline"])

    def test_create_thumbnail_composite(self):
        thumb_dir = os.path.join(self.temp_dir, "thumb")
        scenes = [{"scene_id": 1, "start_seconds": 0.0, "end_seconds": 10.0, "keyframe_seconds": 5.0}]
        # Create without input video to test fallback composite background
        thumb_path = create_thumbnail(
            movie_path="nonexistent.mp4",
            master_story=self.dummy_story,
            scenes=scenes,
            output_dir=thumb_dir,
            language="bn",
            width=640,
            height=360
        )
        self.assertTrue(os.path.isfile(thumb_path))
        self.assertTrue(os.path.isfile(os.path.join(thumb_dir, "concepts.json")))

    def test_automated_qa_validation(self):
        # Create dummy artifacts
        dummy_video = os.path.join(self.temp_dir, "final.mp4")
        dummy_srt = os.path.join(self.temp_dir, "final.srt")
        dummy_wav = os.path.join(self.temp_dir, "narration.wav")

        with open(dummy_video, "wb") as f:
            f.write(b"0" * 2048)
        with open(dummy_srt, "w") as f:
            f.write("1\n00:00:00,000 --> 00:00:05,000\nHello")
        with open(dummy_wav, "wb") as f:
            f.write(b"0" * 500)

        qa_report_path = os.path.join(self.temp_dir, "qa_report.json")
        qa = perform_automated_qa(
            rendered_video_path=dummy_video,
            subtitles_srt_path=dummy_srt,
            master_narration_audio_path=dummy_wav,
            target_duration_minutes=10,
            output_report_path=qa_report_path
        )
        self.assertTrue(os.path.isfile(qa_report_path))
        self.assertTrue(qa["manual_review_required"])
        self.assertTrue(qa["safety_disclaimer_acknowledged"])


if __name__ == "__main__":
    unittest.main()
