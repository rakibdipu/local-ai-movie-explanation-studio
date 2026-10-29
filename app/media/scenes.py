"""Lightweight scene detection and shot boundary identification."""

import os
import subprocess
import json
from typing import List, Dict, Any, Optional
from app.core.logger import get_logger
from app.utils.timecode import seconds_to_hms, parse_time_to_seconds

logger = get_logger()


def detect_scenes_pyscenedetect(
    video_path: str,
    threshold: float = 27.0,
    min_scene_len_sec: float = 2.0
) -> List[Dict[str, Any]]:
    """Detect visual scene cuts using PySceneDetect ContentDetector with low memory footprint."""
    from scenedetect import detect, ContentDetector, AdaptiveDetector

    logger.info(f"Running PySceneDetect ContentDetector on {os.path.basename(video_path)}...")
    scene_list = detect(video_path, ContentDetector(threshold=threshold, min_scene_len=int(min_scene_len_sec * 30)))
    
    scenes = []
    for idx, (start_time, end_time) in enumerate(scene_list):
        start_sec = start_time.get_seconds()
        end_sec = end_time.get_seconds()
        mid_sec = round((start_sec + end_sec) / 2.0, 2)
        scenes.append({
            "scene_id": idx + 1,
            "start": seconds_to_hms(start_sec, include_millis=True),
            "end": seconds_to_hms(end_sec, include_millis=True),
            "start_seconds": round(start_sec, 2),
            "end_seconds": round(end_sec, 2),
            "duration": round(end_sec - start_sec, 2),
            "keyframe_seconds": mid_sec,
        })
    return scenes


def detect_scenes_ffmpeg(
    video_path: str,
    total_duration: float,
    threshold: float = 0.35,
    min_scene_duration: float = 2.5
) -> List[Dict[str, Any]]:
    """Fast fallback scene detection using FFmpeg's internal scene change filter."""
    logger.info(f"Running FFmpeg scene filter (threshold={threshold}) on {os.path.basename(video_path)}...")
    
    # Run ffmpeg to find scene changes
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null",
        "-"
    ]

    try:
        proc = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
        timestamps = [0.0]

        for line in proc.stderr.splitlines():
            if "showinfo" in line and "pts_time:" in line:
                try:
                    parts = line.split("pts_time:")
                    t_str = parts[1].split()[0]
                    t_val = float(t_str)
                    if t_val - timestamps[-1] >= min_scene_duration:
                        timestamps.append(round(t_val, 2))
                except Exception:
                    continue

        if timestamps[-1] < total_duration:
            timestamps.append(round(total_duration, 2))

        scenes = []
        for i in range(len(timestamps) - 1):
            s_start = timestamps[i]
            s_end = timestamps[i + 1]
            s_mid = round((s_start + s_end) / 2.0, 2)
            scenes.append({
                "scene_id": i + 1,
                "start": seconds_to_hms(s_start, include_millis=True),
                "end": seconds_to_hms(s_end, include_millis=True),
                "start_seconds": s_start,
                "end_seconds": s_end,
                "duration": round(s_end - s_start, 2),
                "keyframe_seconds": s_mid,
            })
        return scenes

    except Exception as e:
        logger.warning(f"FFmpeg scene detector failed: {e}, using uniform grid fallback...")
        return generate_uniform_scenes(total_duration, window_size_sec=6.0)


def generate_uniform_scenes(total_duration: float, window_size_sec: float = 6.0) -> List[Dict[str, Any]]:
    """Generate uniform time windows as fallback scene boundaries."""
    scenes = []
    cur = 0.0
    idx = 1
    while cur < total_duration:
        end = min(total_duration, cur + window_size_sec)
        scenes.append({
            "scene_id": idx,
            "start": seconds_to_hms(cur, include_millis=True),
            "end": seconds_to_hms(end, include_millis=True),
            "start_seconds": round(cur, 2),
            "end_seconds": round(end, 2),
            "duration": round(end - cur, 2),
            "keyframe_seconds": round((cur + end) / 2.0, 2),
        })
        idx += 1
        cur = end
    return scenes


def detect_movie_scenes(video_path: str, total_duration: float) -> List[Dict[str, Any]]:
    """Primary scene detection dispatcher: tries PySceneDetect first, falls back to FFmpeg."""
    try:
        scenes = detect_scenes_pyscenedetect(video_path)
        if len(scenes) >= 3:
            logger.info(f"PySceneDetect found {len(scenes)} scenes.")
            return scenes
    except Exception as e:
        logger.warning(f"PySceneDetect detection exception: {e}")

    try:
        scenes = detect_scenes_ffmpeg(video_path, total_duration)
        if len(scenes) >= 3:
            logger.info(f"FFmpeg scene detector found {len(scenes)} scenes.")
            return scenes
    except Exception as e:
        logger.warning(f"FFmpeg scene detection exception: {e}")

    logger.info("Generating uniform scene windows fallback.")
    return generate_uniform_scenes(total_duration)
