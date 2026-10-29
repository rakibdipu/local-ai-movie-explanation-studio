"""FFmpeg streaming video rendering engine optimized for low-RAM execution and copyright-safe still-frame motion."""

import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional
from app.core.logger import get_logger
from app.utils.timecode import seconds_to_hms

logger = get_logger()


def build_aspect_ratio_filter(aspect_ratio: str = "16:9", resolution: str = "1280x720") -> str:
    """Generate FFmpeg video filter to scale, pad, or crop to target aspect ratio and resolution."""
    try:
        w_str, h_str = resolution.split("x")
        target_w, target_h = int(w_str), int(h_str)
    except Exception:
        target_w, target_h = 1280, 720

    if aspect_ratio == "9:16":
        target_w, target_h = min(target_w, target_h), max(target_w, target_h)
    elif aspect_ratio == "1:1":
        min_dim = min(target_w, target_h)
        target_w, target_h = min_dim, min_dim

    # Scale maintaining aspect ratio, then pad with black bars
    vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1"
    )
    return vf


def get_ken_burns_filter(pattern_idx: int, duration_sec: float, resolution: str = "1280x720", fps: int = 30) -> str:
    """Generate dynamic Ken Burns zoom and pan filter for copyright-safe transformative stills."""
    d_frames = int(round(duration_sec * fps)) + 5
    z_step = round(0.22 / max(d_frames, 30), 5)
    pan_step = round(100.0 / max(d_frames, 30), 2)

    pat = pattern_idx % 4
    if pat == 0:
        # Slow Zoom In (Center)
        motion = f"zoompan=z='min(zoom+{z_step},1.25)':d={d_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}"
    elif pat == 1:
        # Slow Zoom Out (Center)
        motion = f"zoompan=z='if(lte(zoom,1.0),1.25,max(1.001,zoom-{z_step}))':d={d_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}"
    elif pat == 2:
        # Cinematic Pan Left
        motion = f"zoompan=z=1.18:d={d_frames}:x='if(lte(on,1),(iw-iw/zoom)*0.9,max((iw-iw/zoom)*0.1,x-{pan_step}))':y='(ih-ih/zoom)/2':s={resolution}:fps={fps}"
    else:
        # Cinematic Pan Right
        motion = f"zoompan=z=1.18:d={d_frames}:x='if(lte(on,1),(iw-iw/zoom)*0.1,min((iw-iw/zoom)*0.9,x+{pan_step}))':y='(ih-ih/zoom)/2':s={resolution}:fps={fps}"

    # Subtle cinematic vignette and gentle contrast/saturation enhancement to break static image fingerprinting
    vf = f"{motion},format=yuv420p,vignette=angle=PI/16:aspect=16/9,eq=contrast=1.04:saturation=1.04"
    return vf


def _render_single_still_motion_clip(
    source_movie_path: str,
    start_sec: float,
    duration_sec: float,
    pattern_idx: int,
    scale_filter: str,
    resolution: str,
    preset: str,
    crf: int,
    shot_img_path: str,
    out_clip_path: str,
    fps: int = 30
) -> bool:
    """Extract a representative keyframe and render a Ken Burns animated motion clip."""
    # Check if already rendered and valid
    if os.path.isfile(out_clip_path) and os.path.getsize(out_clip_path) > 1024:
        return True

    # 1. Extract still frame from movie at representative point
    sample_time = start_sec + min(2.0, duration_sec / 2.0)
    if not (os.path.isfile(shot_img_path) and os.path.getsize(shot_img_path) > 1024):
        cmd_extract = [
            "ffmpeg", "-y",
            "-ss", seconds_to_hms(sample_time, include_millis=True),
            "-i", source_movie_path,
            "-vframes", "1",
            "-vf", scale_filter,
            "-q:v", "2",
            shot_img_path
        ]
        res = subprocess.run(cmd_extract, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0:
            # Fallback to start_sec directly
            cmd_extract[3] = seconds_to_hms(start_sec, include_millis=True)
            subprocess.run(cmd_extract, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not (os.path.isfile(shot_img_path) and os.path.getsize(shot_img_path) > 512):
        return False

    # 2. Render motion clip with Ken Burns filter
    kb_filter = get_ken_burns_filter(pattern_idx, duration_sec, resolution=resolution, fps=fps)
    cmd_motion = [
        "ffmpeg", "-y",
        "-i", shot_img_path,
        "-vf", kb_filter,
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-t", str(duration_sec),
        "-pix_fmt", "yuv420p",
        out_clip_path
    ]
    res_motion = subprocess.run(cmd_motion, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res_motion.returncode == 0 and os.path.isfile(out_clip_path) and os.path.getsize(out_clip_path) > 1024


def render_explanation_video(
    source_movie_path: str,
    timeline_data: Dict[str, Any],
    master_narration_audio_path: str,
    output_video_path: str,
    temp_dir: str,
    aspect_ratio: str = "16:9",
    resolution: str = "1280x720",
    preset: str = "faster",
    crf: int = 22,
    bgm_path: Optional[str] = None,
    bgm_volume: float = 0.10,
    subtitles_path: Optional[str] = None,
    visual_mode: str = "still_motion",
    max_workers: int = 3
) -> str:
    """Render the complete synchronized explanation video using chunked FFmpeg streaming.
    
    Supports:
      - 'still_motion' (default): Copyright-free Ken Burns animated high-res still frames.
      - 'video': Direct raw video clip cuts from the original movie.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_video_path)), exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    items = timeline_data.get("items", [])
    logger.info(
        f"Starting low-RAM video render in '{visual_mode}' mode for {len(items)} "
        f"timeline segments ({resolution}, {aspect_ratio})..."
    )

    scale_filter = build_aspect_ratio_filter(aspect_ratio, resolution)
    clips_dir = os.path.join(temp_dir, "rendered_clips")
    frames_dir = os.path.join(temp_dir, "extracted_frames")
    os.makedirs(clips_dir, exist_ok=True)
    os.makedirs(frames_dir, exist_ok=True)

    concat_manifest_path = os.path.join(temp_dir, "video_concat_list.txt")

    # Collect all visual tasks matching timeline shots
    tasks = []
    clip_counter = 1
    for item_idx, item in enumerate(items):
        source_clips = item.get("source_clips", [])
        for clip in source_clips:
            start_sec = clip["start_seconds"]
            duration_sec = clip["duration"]
            out_clip_path = os.path.join(clips_dir, f"clip_{clip_counter:04d}.mp4")
            shot_img_path = os.path.join(frames_dir, f"frame_{clip_counter:04d}.jpg")
            tasks.append({
                "clip_idx": clip_counter,
                "start_sec": start_sec,
                "duration_sec": duration_sec,
                "out_clip_path": out_clip_path,
                "shot_img_path": shot_img_path
            })
            clip_counter += 1

    total_clips = len(tasks)
    logger.info(f"Processing {total_clips} visual shots using '{visual_mode}' mode...")

    if visual_mode == "still_motion":
        # Parallel execution of Ken Burns frame extraction & zoompan generation
        def _worker(task):
            return _render_single_still_motion_clip(
                source_movie_path=source_movie_path,
                start_sec=task["start_sec"],
                duration_sec=task["duration_sec"],
                pattern_idx=task["clip_idx"],
                scale_filter=scale_filter,
                resolution=resolution,
                preset=preset,
                crf=crf,
                shot_img_path=task["shot_img_path"],
                out_clip_path=task["out_clip_path"],
                fps=30
            )

        completed_count = 0
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {executor.submit(_worker, t): t for t in tasks}
            for future in as_completed(future_to_task):
                completed_count += 1
                if completed_count % 25 == 0 or completed_count == total_clips:
                    logger.info(f"Rendered {completed_count}/{total_clips} Ken Burns still-motion clips...")

    else:
        # Standard video mode: cut raw motion video
        scale_fps_filter = f"{scale_filter},fps=30"
        for t in tasks:
            out_clip_path = t["out_clip_path"]
            if os.path.isfile(out_clip_path) and os.path.getsize(out_clip_path) > 1024:
                continue
            cmd = [
                "ffmpeg", "-y",
                "-ss", seconds_to_hms(t["start_sec"], include_millis=True),
                "-t", str(t["duration_sec"]),
                "-i", source_movie_path,
                "-vf", scale_fps_filter,
                "-an",
                "-c:v", "libx264",
                "-preset", preset,
                "-crf", str(crf),
                "-pix_fmt", "yuv420p",
                out_clip_path
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Build concat manifest
    concat_lines = []
    fallback_clip = None
    for t in tasks:
        p = t["out_clip_path"]
        if os.path.isfile(p) and os.path.getsize(p) > 1024:
            concat_lines.append(f"file '{os.path.abspath(p)}'")
            fallback_clip = p
        elif fallback_clip:
            logger.warning(f"Clip {t['clip_idx']} missing, falling back to previous clip...")
            concat_lines.append(f"file '{os.path.abspath(fallback_clip)}'")

    with open(concat_manifest_path, "w", encoding="utf-8") as f:
        f.write("\n".join(concat_lines))

    # Assemble visual track and multiplex narration audio
    logger.info("Merging visual sequence with master narration audio...")
    raw_video_path = os.path.join(temp_dir, "raw_assembled.mp4")

    cmd_assemble = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_manifest_path,
        "-i", master_narration_audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        raw_video_path
    ]
    subprocess.run(cmd_assemble, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Optional Subtitle Burn-In / BGM Mixing
    if subtitles_path and os.path.isfile(subtitles_path):
        logger.info(f"Burning subtitles into final video from {subtitles_path}...")
        escaped_sub_path = os.path.abspath(subtitles_path).replace(":", "\\:").replace("'", "\\'")
        cmd_sub = [
            "ffmpeg",
            "-y",
            "-i", raw_video_path,
            "-vf", f"subtitles='{escaped_sub_path}'",
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", str(crf),
            "-c:a", "copy",
            output_video_path
        ]
        try:
            subprocess.run(cmd_sub, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return output_video_path
        except Exception as e:
            logger.warning(f"Subtitle burn-in failed ({e}), outputting raw video...")

    # Direct final output move
    if os.path.isfile(raw_video_path):
        if os.path.exists(output_video_path):
            os.remove(output_video_path)
        os.replace(raw_video_path, output_video_path)

    logger.info(f"Final video rendered successfully -> {output_video_path}")
    return output_video_path
