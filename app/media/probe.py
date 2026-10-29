"""Media inspection using FFprobe."""

import json
import subprocess
import os
from typing import Dict, Any, List, Optional
from app.core.logger import get_logger

logger = get_logger()


def probe_media_file(file_path: str) -> Dict[str, Any]:
    """Inspect media file using ffprobe and return structured metadata.
    
    Extracts:
    - duration
    - resolution (width, height)
    - FPS
    - video codec
    - audio codec
    - audio streams & languages
    - subtitle streams & languages
    - bitrate
    - frame count
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Media file not found: {file_path}")

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path
    ]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        probe_data = json.loads(proc.stdout)
    except Exception as e:
        logger.error(f"FFprobe execution failed for {file_path}: {e}")
        raise RuntimeError(f"FFprobe failed to inspect media: {e}")

    format_info = probe_data.get("format", {})
    streams = probe_data.get("streams", [])

    duration = float(format_info.get("duration", 0.0))
    bitrate = int(format_info.get("bit_rate", 0)) if format_info.get("bit_rate") else 0
    size_bytes = int(format_info.get("size", 0)) if format_info.get("size") else os.path.getsize(file_path)

    video_streams = []
    audio_streams = []
    subtitle_streams = []

    for s in streams:
        codec_type = s.get("codec_type")
        tags = s.get("tags", {})
        language = tags.get("language", "und")

        if codec_type == "video" and not s.get("disposition", {}).get("attached_pic", 0):
            # Parse frame rate
            fps = 30.0
            r_frame_rate = s.get("r_frame_rate", "30/1")
            if "/" in r_frame_rate:
                num, den = r_frame_rate.split("/")
                if float(den) > 0:
                    fps = round(float(num) / float(den), 2)
            elif r_frame_rate:
                fps = float(r_frame_rate)

            v_info = {
                "index": s.get("index"),
                "codec_name": s.get("codec_name"),
                "width": int(s.get("width", 0)),
                "height": int(s.get("height", 0)),
                "fps": fps,
                "aspect_ratio": s.get("display_aspect_ratio", f"{s.get('width', 0)}:{s.get('height', 0)}"),
                "duration": float(s.get("duration", duration)),
                "bitrate": int(s.get("bit_rate", 0)) if s.get("bit_rate") else 0,
            }
            video_streams.append(v_info)

        elif codec_type == "audio":
            a_info = {
                "index": s.get("index"),
                "codec_name": s.get("codec_name"),
                "channels": int(s.get("channels", 2)),
                "sample_rate": int(s.get("sample_rate", 44100)),
                "language": language,
                "title": tags.get("title", ""),
                "bitrate": int(s.get("bit_rate", 0)) if s.get("bit_rate") else 0,
            }
            audio_streams.append(a_info)

        elif codec_type == "subtitle":
            sub_info = {
                "index": s.get("index"),
                "codec_name": s.get("codec_name"),
                "language": language,
                "title": tags.get("title", ""),
                "disposition": s.get("disposition", {}),
            }
            subtitle_streams.append(sub_info)

    primary_video = video_streams[0] if video_streams else {}
    primary_audio = audio_streams[0] if audio_streams else {}

    result = {
        "file_path": file_path,
        "filename": os.path.basename(file_path),
        "file_size_mb": round(size_bytes / (1024 * 1024), 2),
        "duration_seconds": duration,
        "bitrate_kbps": round(bitrate / 1000, 2),
        "video": {
            "codec": primary_video.get("codec_name", "unknown"),
            "width": primary_video.get("width", 0),
            "height": primary_video.get("height", 0),
            "resolution": f"{primary_video.get('width', 0)}x{primary_video.get('height', 0)}",
            "fps": primary_video.get("fps", 30.0),
            "streams_count": len(video_streams),
        },
        "audio": {
            "codec": primary_audio.get("codec_name", "unknown"),
            "channels": primary_audio.get("channels", 2),
            "sample_rate": primary_audio.get("sample_rate", 44100),
            "streams_count": len(audio_streams),
            "languages": [a["language"] for a in audio_streams],
            "streams": audio_streams,
        },
        "subtitles": {
            "streams_count": len(subtitle_streams),
            "languages": [s["language"] for s in subtitle_streams],
            "streams": subtitle_streams,
        }
    }
    return result
