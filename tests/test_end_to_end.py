"""End-to-End integration test running the complete 10-stage studio pipeline on a synthetic movie."""

import os
import shutil
import subprocess
import tempfile
import unittest
from app.core.config import Config, ExplanationParams
from app.orchestrator import StudioOrchestrator


def create_synthetic_test_movie(output_mp4: str, duration_sec: int = 15) -> str:
    """Generate a lightweight test video with video stream, audio tone, and embedded subtitles."""
    os.makedirs(os.path.dirname(os.path.abspath(output_mp4)), exist_ok=True)
    
    # 1. Create temporary SRT subtitle
    srt_temp = output_mp4 + ".srt"
    with open(srt_temp, "w", encoding="utf-8") as f:
        f.write("""1
00:00:01,000 --> 00:00:05,000
A mysterious detective arrives at the rain-soaked docks.

2
00:00:06,000 --> 00:00:10,000
He finds a secret ledger containing shocking evidence against the syndicate.

3
00:00:11,000 --> 00:00:14,000
Suddenly, the mastermind is revealed in the shadows.
""")

    # 2. Render 15s color bar video with sine audio and embedded subtitle
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration_sec}:size=640x360:rate=24",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration_sec}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        "-shortest",
        output_mp4
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_mp4


class TestEndToEndStudio(unittest.TestCase):

    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.movie_file = os.path.join(self.temp_root, "input", "test_movie.mp4")
        create_synthetic_test_movie(self.movie_file, duration_sec=15)

        # Config pointing to temp directories
        self.config_data = {
            "project": {
                "input_dir": os.path.join(self.temp_root, "input"),
                "output_dir": os.path.join(self.temp_root, "output"),
                "projects_dir": os.path.join(self.temp_root, "projects"),
                "temp_dir": os.path.join(self.temp_root, "temp")
            },
            "video": {
                "default_resolution": "640x360",
                "aspect_ratio": "16:9",
                "preset": "ultrafast",
                "crf": 26
            },
            "story": {
                "default_duration_minutes": 1,
                "chunk_duration_seconds": 10,
                "chunk_overlap_seconds": 2
            },
            "narration": {
                "default_language": "bn",
                "default_style": "cinematic_storytelling",
                "speed": 1.0
            },
            "tts": {
                "preferred_engine": "system",
                "fallback_engine": "system"
            },
            "processing": {
                "min_disk_free_gb": 0.1
            }
        }
        self.config = Config()
        self.config.data = self.config_data

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_complete_studio_pipeline_bangla(self):
        params = ExplanationParams(
            language="bn",
            duration_minutes=1,
            narration_style="cinematic_storytelling",
            aspect_ratio="16:9",
            resolution="640x360"
        )

        orchestrator = StudioOrchestrator(self.movie_file, self.config, params)
        result = orchestrator.run_pipeline(resume_mode=False)

        deliverables = result["deliverables"]
        self.assertIn("video", deliverables)
        self.assertIn("thumbnail", deliverables)
        self.assertIn("script", deliverables)
        self.assertIn("subtitles_srt", deliverables)
        self.assertIn("metadata", deliverables)

        # Verify physical existence and non-zero size of all final outputs
        for name, path in deliverables.items():
            if name == "delivery_folder":
                self.assertTrue(os.path.isdir(path), f"Delivery folder missing at {path}")
            else:
                self.assertTrue(os.path.isfile(path), f"Deliverable {name} missing at {path}")
                self.assertTrue(os.path.getsize(path) > 0, f"Deliverable {name} is empty at {path}")


        # Verify state is 100% completed
        summary = orchestrator.state.get_progress_summary()
        self.assertEqual(summary["percentage"], 100.0)
        self.assertEqual(summary["completed_stages"], summary["total_stages"])

    def test_complete_studio_pipeline_hindi(self):
        params = ExplanationParams(
            language="hi",
            duration_minutes=1,
            narration_style="mystery_detective",
            aspect_ratio="16:9",
            resolution="640x360"
        )

        orchestrator = StudioOrchestrator(self.movie_file, self.config, params)
        result = orchestrator.run_pipeline(resume_mode=False)

        deliverables = result["deliverables"]
        self.assertTrue(os.path.isfile(deliverables["video"]))
        self.assertTrue(os.path.isfile(deliverables["thumbnail"]))
        self.assertTrue(os.path.isfile(deliverables["script"]))


if __name__ == "__main__":
    unittest.main()
