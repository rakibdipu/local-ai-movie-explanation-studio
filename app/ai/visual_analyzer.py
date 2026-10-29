"""Selective visual keyframe extraction and verification."""

import os
import subprocess
from typing import List, Dict, Any, Optional
from app.core.logger import get_logger
from app.utils.timecode import seconds_to_hms

logger = get_logger()


def extract_frame_at_timestamp(
    video_path: str,
    timestamp_sec: float,
    output_image_path: str,
    width: int = 1280,
    height: int = 720
) -> Optional[str]:
    """Extract a single high-quality frame at exact second offset using FFmpeg."""
    os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
    
    time_str = seconds_to_hms(timestamp_sec, include_millis=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", time_str,
        "-i", video_path,
        "-vframes", "1",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-q:v", "2",
        output_image_path
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.isfile(output_image_path) and os.path.getsize(output_image_path) > 1000:
            return output_image_path
    except Exception as e:
        logger.warning(f"Failed to extract frame at {time_str}: {e}")
    return None


def extract_scene_keyframes(
    video_path: str,
    scene: Dict[str, Any],
    output_dir: str
) -> Dict[str, str]:
    """Extract opening, middle, and closing keyframes for a pivotal scene."""
    os.makedirs(output_dir, exist_ok=True)
    scene_id = scene.get("scene_id", 1)
    start_sec = scene.get("start_seconds", 0.0)
    end_sec = scene.get("end_seconds", start_sec + 5.0)
    mid_sec = round((start_sec + end_sec) / 2.0, 2)

    frames = {}
    
    # 1. Opening frame (slightly offset by 0.5s to avoid black cut)
    open_sec = min(end_sec - 0.1, start_sec + 0.5)
    open_path = os.path.join(output_dir, f"scene_{scene_id:03d}_open.jpg")
    if extract_frame_at_timestamp(video_path, open_sec, open_path):
        frames["open"] = open_path

    # 2. Middle frame
    mid_path = os.path.join(output_dir, f"scene_{scene_id:03d}_mid.jpg")
    if extract_frame_at_timestamp(video_path, mid_sec, mid_path):
        frames["mid"] = mid_path

    # 3. Closing frame
    close_sec = max(start_sec + 0.1, end_sec - 0.5)
    close_path = os.path.join(output_dir, f"scene_{scene_id:03d}_close.jpg")
    if extract_frame_at_timestamp(video_path, close_sec, close_path):
        frames["close"] = close_path

    return frames
