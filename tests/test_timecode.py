import unittest
from app.utils.timecode import (
    seconds_to_hms,
    seconds_to_srt_time,
    seconds_to_vtt_time,
    seconds_to_ass_time,
    parse_time_to_seconds,
    format_duration_human
)


class TestTimecodeUtilities(unittest.TestCase):

    def test_seconds_to_hms(self):
        self.assertEqual(seconds_to_hms(0), "00:00:00")
        self.assertEqual(seconds_to_hms(65), "00:01:05")
        self.assertEqual(seconds_to_hms(3661), "01:01:01")
        self.assertEqual(seconds_to_hms(75.5, include_millis=True), "00:01:15.500")

    def test_seconds_to_srt_time(self):
        self.assertEqual(seconds_to_srt_time(83.456), "00:01:23,456")
        self.assertEqual(seconds_to_srt_time(3600), "01:00:00,000")

    def test_seconds_to_vtt_time(self):
        self.assertEqual(seconds_to_vtt_time(83.456), "00:01:23.456")

    def test_seconds_to_ass_time(self):
        self.assertEqual(seconds_to_ass_time(83.45), "0:01:23.45")

    def test_parse_time_to_seconds(self):
        self.assertEqual(parse_time_to_seconds("01:23:45.500"), 5025.5)
        self.assertEqual(parse_time_to_seconds("23:45"), 1425.0)
        self.assertEqual(parse_time_to_seconds("45"), 45.0)
        self.assertEqual(parse_time_to_seconds("20m"), 1200.0)
        self.assertEqual(parse_time_to_seconds("1h 30m"), 5400.0)
        self.assertEqual(parse_time_to_seconds("15 মিনিট"), 900.0)
        self.assertEqual(parse_time_to_seconds("10 मिनट"), 600.0)

    def test_format_duration_human(self):
        self.assertEqual(format_duration_human(45), "45s")
        self.assertEqual(format_duration_human(125), "2m 5s")
        self.assertEqual(format_duration_human(3722), "1h 2m 2s")


if __name__ == "__main__":
    unittest.main()
