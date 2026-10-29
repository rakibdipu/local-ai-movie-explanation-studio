"""Subtitle generator producing synchronized SRT and ASS subtitle tracks for the explanation video."""

import os
from typing import Dict, Any, List, Optional
from app.core.logger import get_logger
from app.utils.timecode import seconds_to_srt_time, seconds_to_ass_time

logger = get_logger()


def generate_explanation_subtitles(
    timeline_data: Dict[str, Any],
    output_srt_path: str,
    output_ass_path: Optional[str] = None,
    font_name: str = "Noto Sans",
    font_size: int = 22
) -> Dict[str, str]:
    """Generate synchronized SRT and styled ASS subtitles from narration timeline items."""
    os.makedirs(os.path.dirname(os.path.abspath(output_srt_path)), exist_ok=True)
    items = timeline_data.get("items", [])

    srt_entries = []
    ass_dialogues = []

    sub_index = 1
    for item in items:
        text = item.get("narration_text", "").strip()
        if not text:
            continue

        item_start = float(item.get("timeline_start_seconds", 0.0))
        item_duration = float(item.get("duration_seconds", 5.0))
        item_end = item_start + item_duration

        # Break long sentences into natural 4-7 second reading chunks
        sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
        if not sentences:
            sentences = [text]

        chunk_time = item_duration / max(1, len(sentences))

        for s_idx, sent in enumerate(sentences):
            c_start = item_start + (s_idx * chunk_time)
            c_end = min(item_end, c_start + chunk_time)
            
            srt_start_str = seconds_to_srt_time(c_start)
            srt_end_str = seconds_to_srt_time(c_end)
            srt_entries.append(f"{sub_index}\n{srt_start_str} --> {srt_end_str}\n{sent}\n")

            ass_start_str = seconds_to_ass_time(c_start)
            ass_end_str = seconds_to_ass_time(c_end)
            ass_dialogues.append(f"Dialogue: 0,{ass_start_str},{ass_end_str},Default,,0,0,0,,{sent}")

            sub_index += 1

    # Write SRT
    with open(output_srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_entries))
    logger.info(f"Generated SRT subtitles ({len(srt_entries)} cues) -> {output_srt_path}")

    # Write ASS if requested
    results = {"srt": output_srt_path}
    if output_ass_path:
        ass_header = f"""[Script Info]
Title: Movie Explanation Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,20,20,25,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(ass_header + "\n".join(ass_dialogues) + "\n")
        results["ass"] = output_ass_path
        logger.info(f"Generated ASS subtitles -> {output_ass_path}")

    return results
