"""Supporting video clip selection and visual pacing optimization."""

import re
from typing import List, Dict, Any, Optional, Tuple
from app.core.logger import get_logger
from app.utils.timecode import seconds_to_hms, parse_time_to_seconds

logger = get_logger()


def find_best_source_window_for_segment(
    segment: Dict[str, Any],
    chunk_analyses: Optional[List[Dict[str, Any]]],
    total_movie_duration: float,
    fallback_start: float,
    fallback_end: float
) -> Tuple[float, float]:
    """Identify the optimal movie timeframe that semantically matches the narration segment."""
    if not chunk_analyses:
        return (fallback_start, fallback_end)

    seg_text = f"{segment.get('narration_text', '')} {segment.get('clean_text', '')}".lower()
    act = str(segment.get("act", "")).lower()

    # Target relative narrative position in movie (0.0 to 1.0)
    act_target_pos = {
        "hook": 0.05,
        "setup": 0.15,
        "inciting_incident": 0.25,
        "investigation": 0.40,
        "escalation": 0.55,
        "revelations": 0.70,
        "climax": 0.85,
        "resolution": 0.95,
        "outro": 0.98
    }.get(act, None)

    best_chunk = None
    best_score = -1.0

    # Extract words from segment text
    seg_words = set(re.findall(r"\w+", seg_text))
    # Filter very short words
    seg_words = {w for w in seg_words if len(w) > 3}

    for idx, chunk in enumerate(chunk_analyses):
        # Calculate chunk start and end in seconds
        chk_start = chunk.get("start_seconds")
        if chk_start is None:
            chk_start = parse_time_to_seconds(chunk.get("start", 0.0))
        chk_end = chunk.get("end_seconds")
        if chk_end is None:
            chk_end = parse_time_to_seconds(chunk.get("end", chk_start + 120.0))

        chk_start = float(chk_start)
        chk_end = float(chk_end)
        if chk_end <= chk_start:
            chk_end = chk_start + 60.0

        score = 0.0

        # 1. Character matches (weight: 3.0 points each)
        for char in chunk.get("characters", []):
            c_name = char.get("character") or char.get("name") if isinstance(char, dict) else str(char)
            if c_name and len(c_name) > 2 and c_name.lower() in seg_text:
                score += 3.0

        # 2. Key events / summary keyword overlap (weight: 1.0 per word)
        chunk_text = f"{chunk.get('summary', '')} {' '.join(chunk.get('events', []))}".lower()
        chunk_words = set(re.findall(r"\w+", chunk_text))
        overlap = seg_words.intersection(chunk_words)
        score += min(5.0, len(overlap) * 0.8)

        # 3. Chronological proximity to narrative act (weight: up to 2.0 points)
        # Only add proximity bonus if there was an actual character or keyword match
        chunk_pos = chk_start / max(1.0, total_movie_duration)
        if act_target_pos is not None and score > 0.0:
            dist = abs(chunk_pos - act_target_pos)
            score += max(0.0, 2.0 * (1.0 - dist * 2.0))

        if score > best_score:
            best_score = score
            best_chunk = (chk_start, chk_end)

    if best_chunk and best_score >= 2.0:
        logger.debug(f"Matched segment {segment.get('segment_id')} to movie window {best_chunk[0]}s-{best_chunk[1]}s (Score: {best_score:.2f})")
        return best_chunk

    return (fallback_start, fallback_end)


def select_supporting_clips_for_segment(
    segment: Dict[str, Any],
    scenes: List[Dict[str, Any]],
    total_movie_duration: float,
    max_single_shot_sec: float = 8.5,
    min_single_shot_sec: float = 3.5,
    chunk_analyses: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Select chronologically progressive visual clips from the movie matching the narration segment's timeframe.
    
    Guarantees:
    1. Exact frame-accurate duration matching (zero cumulative drift between audio and video).
    2. Emotion-aware cutting rhythm (action/climax cuts faster; suspense/mystery holds longer).
    3. Natural scene cut boundary snapping via PySceneDetect/FFmpeg scene detection.
    4. Semantic character and event matching when chunk_analyses are provided.
    """
    target_duration = float(segment.get("actual_duration_seconds") or segment.get("estimated_seconds") or 15.0)
    raw_src_start = float(segment.get("source_start_seconds", 0.0))
    raw_src_end = float(segment.get("source_end_seconds", min(total_movie_duration, raw_src_start + 138.0)))

    # Semantic scene resolution
    if segment.get("curated") or segment.get("explicit_window"):
        src_start, src_end = raw_src_start, raw_src_end
    else:
        src_start, src_end = find_best_source_window_for_segment(
            segment=segment,
            chunk_analyses=chunk_analyses,
            total_movie_duration=total_movie_duration,
            fallback_start=raw_src_start,
            fallback_end=raw_src_end
        )
    window_len = max(target_duration, src_end - src_start)

    # Emotion-aware shot pacing
    emotion = str(segment.get("emotion", "")).lower()
    if any(k in emotion for k in ["action", "climax"]):
        target_shot_len = 4.5
    elif any(k in emotion for k in ["suspense", "mystery", "revelation"]):
        target_shot_len = 7.5
    else:
        target_shot_len = 6.0

    num_shots = max(2, min(5, int(round(target_duration / target_shot_len))))
    base_shot_duration = target_duration / num_shots

    clips: List[Dict[str, Any]] = []
    accumulated_duration = 0.0

    for shot_idx in range(num_shots):
        is_last_shot = (shot_idx == num_shots - 1)
        progress_ratio = shot_idx / num_shots
        shot_src_start = src_start + (progress_ratio * max(0.0, window_len - base_shot_duration))
        
        # Calculate shot duration (guaranteeing exact total sum)
        if is_last_shot:
            this_shot_len = round(target_duration - accumulated_duration, 2)
        else:
            this_shot_len = round(base_shot_duration, 2)

        # Snap to closest scene boundary within 2.5s for a natural cut
        for s in scenes:
            s_start = s.get("start_seconds", 0.0)
            if abs(s_start - shot_src_start) <= 2.5:
                shot_src_start = s_start
                break

        # Ensure shot does not exceed movie bounds
        shot_src_start = max(0.0, min(total_movie_duration - this_shot_len, shot_src_start))
        clip_end = round(shot_src_start + this_shot_len, 2)
        actual_shot_len = round(clip_end - shot_src_start, 2)

        clips.append({
            "clip_id": len(clips) + 1,
            "scene_id": shot_idx + 1,
            "start_seconds": round(shot_src_start, 2),
            "end_seconds": round(clip_end, 2),
            "duration": actual_shot_len,
            "start_timecode": seconds_to_hms(shot_src_start, include_millis=True),
            "end_timecode": seconds_to_hms(clip_end, include_millis=True),
        })

        accumulated_duration += actual_shot_len

    # Final calibration to ensure exact floating-point match down to 0.01s
    total_clip_dur = round(sum(c["duration"] for c in clips), 2)
    diff = round(target_duration - total_clip_dur, 2)
    if diff != 0 and clips:
        clips[-1]["duration"] = round(clips[-1]["duration"] + diff, 2)
        clips[-1]["end_seconds"] = round(clips[-1]["start_seconds"] + clips[-1]["duration"], 2)
        clips[-1]["end_timecode"] = seconds_to_hms(clips[-1]["end_seconds"], include_millis=True)

    return clips
