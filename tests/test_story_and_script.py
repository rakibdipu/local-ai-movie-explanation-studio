import unittest
import os
import shutil
import tempfile
from app.ai.provider import LocalHeuristicAIProvider
from app.ai.story_mapper import build_master_story_map
from app.ai.script_writer import generate_explanation_script, calculate_target_word_count


class TestStoryAndScript(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ai_provider = LocalHeuristicAIProvider()
        self.sample_chunks = [
            {
                "chunk_id": 1,
                "start": "00:00:00",
                "end": "00:05:00",
                "start_seconds": 0.0,
                "end_seconds": 300.0,
                "summary": "Detective Roy arrives in the rainy city and visits the crime scene.",
                "characters": ["Roy", "Chief Harris"],
                "importance": 0.90
            },
            {
                "chunk_id": 2,
                "start": "00:05:00",
                "end": "00:10:00",
                "start_seconds": 300.0,
                "end_seconds": 600.0,
                "summary": "Roy interrogates Elena, discovering a hidden ledger with corrupt names.",
                "characters": ["Roy", "Elena"],
                "importance": 0.85
            },
            {
                "chunk_id": 3,
                "start": "00:10:00",
                "end": "00:15:00",
                "start_seconds": 600.0,
                "end_seconds": 900.0,
                "summary": "A tense chase through the harbor where the mastermind is unmasked.",
                "characters": ["Roy", "Harris"],
                "importance": 0.95
            }
        ]

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_build_master_story_map(self):
        story_map_path = os.path.join(self.temp_dir, "master_story.json")
        story_map = build_master_story_map(self.sample_chunks, story_map_path, self.ai_provider)
        self.assertIn("setup", story_map)
        self.assertIn("climax", story_map)
        self.assertIn("resolution", story_map)
        self.assertTrue(os.path.isfile(story_map_path))

    def test_calculate_target_word_count(self):
        w_en = calculate_target_word_count(20, "en")
        w_bn = calculate_target_word_count(20, "bn")
        w_hi = calculate_target_word_count(20, "hi")
        self.assertTrue(2500 <= w_en <= 3200)
        self.assertTrue(2400 <= w_bn <= 3000)
        self.assertTrue(2400 <= w_hi <= 3100)

    def test_generate_script_bangla(self):
        story_map_path = os.path.join(self.temp_dir, "master_story.json")
        story_map = build_master_story_map(self.sample_chunks, story_map_path, self.ai_provider)

        script_dir = os.path.join(self.temp_dir, "scripts")
        manifest = generate_explanation_script(
            master_story=story_map,
            chunk_analyses=self.sample_chunks,
            target_duration_minutes=10,
            language="bn",
            narration_style="cinematic_storytelling",
            output_dir=script_dir,
            ai_provider=self.ai_provider
        )
        self.assertEqual(manifest["language"], "bn")
        self.assertTrue(manifest["total_segments"] >= 5)
        self.assertTrue(os.path.isfile(os.path.join(script_dir, "script_bn.txt")))

    def test_generate_script_hindi(self):
        story_map_path = os.path.join(self.temp_dir, "master_story.json")
        story_map = build_master_story_map(self.sample_chunks, story_map_path, self.ai_provider)

        script_dir = os.path.join(self.temp_dir, "scripts")
        manifest = generate_explanation_script(
            master_story=story_map,
            chunk_analyses=self.sample_chunks,
            target_duration_minutes=15,
            language="hi",
            narration_style="cinematic_storytelling",
            output_dir=script_dir,
            ai_provider=self.ai_provider
        )
        self.assertEqual(manifest["language"], "hi")
        self.assertTrue(manifest["total_segments"] >= 5)
        self.assertTrue(os.path.isfile(os.path.join(script_dir, "script_hi.txt")))


if __name__ == "__main__":
    unittest.main()
