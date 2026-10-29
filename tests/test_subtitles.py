import unittest
from app.media.subtitles import clean_subtitle_text, normalize_subtitles, create_chunks_from_timeline


class TestSubtitleProcessing(unittest.TestCase):

    def test_clean_subtitle_text(self):
        # HTML tag stripping
        self.assertEqual(clean_subtitle_text("<i>Hello <b>World</b></i>"), "Hello World")

        # ASS style tag stripping
        self.assertEqual(clean_subtitle_text("{\\an8\\pos(100,200)}This is a top title"), "This is a top title")

        # Hearing impaired tag stripping
        self.assertEqual(clean_subtitle_text("[MUSIC PLAYING] John enters the house. (DOOR CREAKS)"), "John enters the house.")
        self.assertEqual(clean_subtitle_text("♪ Romantic melody ♪"), "")

        # Speaker tag normalization
        self.assertEqual(clean_subtitle_text("DETECTIVE: Where were you last night?"), "Where were you last night?")

    def test_normalize_subtitles(self):
        raw_cues = [
            {"id": 1, "start": 10.0, "end": 15.0, "duration": 5.0, "text": "Hello John"},
            {"id": 2, "start": 15.0, "end": 20.0, "duration": 5.0, "text": "Hello John"},  # Duplicate
            {"id": 3, "start": 21.0, "end": 25.0, "duration": 4.0, "text": "How are you?"}
        ]
        normalized = normalize_subtitles(raw_cues)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["text"], "Hello John")
        self.assertEqual(normalized[0]["end"], 20.0)
        self.assertEqual(normalized[1]["text"], "How are you?")

    def test_create_chunks_from_timeline(self):
        cues = [
            {"id": 1, "start": 10.0, "end": 15.0, "duration": 5.0, "text": "Scene 1 begins."},
            {"id": 2, "start": 180.0, "end": 185.0, "duration": 5.0, "text": "Scene 2 begins."},
            {"id": 3, "start": 400.0, "end": 405.0, "duration": 5.0, "text": "Scene 3 begins."},
        ]
        chunks = create_chunks_from_timeline(cues, total_duration=600.0, chunk_duration_sec=300.0, overlap_sec=30.0)
        self.assertTrue(len(chunks) >= 2)
        self.assertEqual(chunks[0]["chunk_id"], 1)
        self.assertTrue(chunks[0]["dialogue_count"] >= 1)


if __name__ == "__main__":
    unittest.main()
