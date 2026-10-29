"""Timeline synthesis connecting narration audio segments to visual source clips."""

import os
from typing import List, Dict, Any, Optional
from app.editing.clip_selector import select_supporting_clips_for_segment
from app.core.logger import get_logger
from app.utils.files import safe_write_json

logger = get_logger()


def build_explanation_timeline(
    voice_manifest: Dict[str, Any],
    scenes: List[Dict[str, Any]],
    total_movie_duration: float,
    output_path: str,
    chunk_analyses: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Construct full video-audio synchronization timeline mapping."""
    segments = voice_manifest.get("segments", [])
    logger.info(f"Building synchronized timeline for {len(segments)} narration segments...")

    timeline_items = []
    accumulated_timeline_sec = 0.0
    max_segment_drift = 0.0

    for idx, seg in enumerate(segments):
        seg_id = seg.get("segment_id", idx + 1)
        audio_duration = float(seg.get("actual_duration_seconds", seg.get("estimated_seconds", 15.0)))
        
        # Select matching visual clips for this narration segment with semantic scene analysis
        clips = select_supporting_clips_for_segment(
            segment=seg,
            scenes=scenes,
            total_movie_duration=total_movie_duration,
            chunk_analyses=chunk_analyses
        )

        clips_total_dur = round(sum(c["duration"] for c in clips), 2)
        segment_drift = round(abs(clips_total_dur - round(audio_duration, 2)), 3)
        if segment_drift > max_segment_drift:
            max_segment_drift = segment_drift

        timeline_start = round(accumulated_timeline_sec, 2)
        timeline_end = round(accumulated_timeline_sec + audio_duration, 2)

        item = {
            "segment_id": seg_id,
            "act": seg.get("act", "scene"),
            "narration_text": seg.get("narration_text", ""),
            "audio_file": seg.get("audio_file", ""),
            "timeline_start_seconds": timeline_start,
            "timeline_end_seconds": timeline_end,
            "duration_seconds": round(audio_duration, 2),
            "clips_total_duration_seconds": clips_total_dur,
            "av_sync_drift_seconds": segment_drift,
            "source_clips": clips
        }
        timeline_items.append(item)
        accumulated_timeline_sec += audio_duration

    timeline_data = {
        "total_duration_seconds": round(accumulated_timeline_sec, 2),
        "total_segments": len(timeline_items),
        "total_clips": sum(len(it["source_clips"]) for it in timeline_items),
        "av_sync_max_drift_seconds": max_segment_drift,
        "sync_verified": max_segment_drift < 0.1,
        "items": timeline_items
    }

    safe_write_json(output_path, timeline_data)
    logger.info(
        f"Timeline constructed: {len(timeline_items)} segments, "
        f"{timeline_data['total_clips']} clips, total length: {round(accumulated_timeline_sec, 1)}s "
        f"(Audio-Visual drift: {max_segment_drift}s). Saved to {output_path}"
    )

    return timeline_data
