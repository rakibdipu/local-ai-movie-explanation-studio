import unittest
from app.core.config import parse_natural_prompt


class TestPromptParser(unittest.TestCase):

    def test_parse_hindi_prompt(self):
        p = parse_natural_prompt("Create a 20 minute Hindi movie explanation")
        self.assertEqual(p.language, "hi")
        self.assertEqual(p.duration_minutes, 20)
        self.assertEqual(p.narration_style, "cinematic_storytelling")

    def test_parse_bangla_prompt(self):
        p = parse_natural_prompt("Bangla, cinematic storytelling, 18 minutes")
        self.assertEqual(p.language, "bn")
        self.assertEqual(p.duration_minutes, 18)
        self.assertEqual(p.narration_style, "cinematic_storytelling")

    def test_parse_fast_paced_english_prompt(self):
        p = parse_natural_prompt("Explain this movie in English in approximately 10 minutes with fast-paced youtube style")
        self.assertEqual(p.language, "en")
        self.assertEqual(p.duration_minutes, 10)
        self.assertEqual(p.narration_style, "fast_paced_youtube")

    def test_parse_vertical_shorts_prompt(self):
        p = parse_natural_prompt("Make 9:16 vertical shorts recap in Hindi for 15m")
        self.assertEqual(p.language, "hi")
        self.assertEqual(p.duration_minutes, 15)
        self.assertEqual(p.aspect_ratio, "9:16")
        self.assertEqual(p.resolution, "720x1280")


if __name__ == "__main__":
    unittest.main()
