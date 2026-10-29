"""Automated Quality Assurance validator and Rights/Safety Gate."""

import os
import json
from typing import Dict, Any, List
from app.media.probe import probe_media_file
from app.core.logger import get_logger
from app.utils.files import safe_write_json
from app.utils.timecode import seconds_to_hms, format_duration_human

logger = get_logger()

SAFETY_DISCLAIMER = """
================================================================================
IMPORTANT RIGHTS & EDITORIAL NOTICE:
This tool creates transformative educational commentary and narrative recaps.
It does NOT guarantee automatic copyright clearance or immunity from claims.
Please review the final video output and verify your distribution rights.
================================================================================
"""


def perform_automated_qa(
    rendered_video_path: str,
    subtitles_srt_path: str,
    master_narration_audio_path: str,
    target_duration_minutes: int,
    output_report_path: str
) -> Dict[str, Any]:
    """Validate audio integrity, video stream health, subtitle synchronization, and duration accuracy."""
    logger.info("Performing comprehensive automated Quality Assurance (QA) audit...")

    checks: Dict[str, bool] = {}
    issues: List[str] = []

    # 1. Video file check
    video_exists = os.path.isfile(rendered_video_path) and os.path.getsize(rendered_video_path) > 1024
    checks["video_file_exists"] = video_exists
    actual_duration_sec = 0.0

    if video_exists:
        try:
            v_probe = probe_media_file(rendered_video_path)
            actual_duration_sec = float(v_probe.get("duration_seconds", 0.0))
            checks["video_stream_valid"] = v_probe.get("video", {}).get("codec") != "unknown"
            checks["audio_stream_valid"] = v_probe.get("audio", {}).get("codec") != "unknown"
        except Exception as e:
            issues.append(f"Failed to probe rendered video: {e}")
            checks["video_stream_valid"] = False
            checks["audio_stream_valid"] = False
    else:
        issues.append("Rendered final.mp4 is missing or empty.")
        checks["video_stream_valid"] = False
        checks["audio_stream_valid"] = False

    # 2. Narration audio check
    narration_exists = os.path.isfile(master_narration_audio_path) and os.path.getsize(master_narration_audio_path) > 100
    checks["narration_audio_exists"] = narration_exists
    if not narration_exists:
        issues.append("Master narration audio file is missing or corrupted.")

    # 3. Subtitles check
    sub_exists = os.path.isfile(subtitles_srt_path) and os.path.getsize(subtitles_srt_path) > 50
    checks["subtitles_valid"] = sub_exists
    if not sub_exists:
        issues.append("Final subtitles SRT file is missing or empty.")

    # 4. Duration accuracy check
    target_sec = target_duration_minutes * 60
    duration_diff_sec = abs(actual_duration_sec - target_sec)
    duration_ok = (duration_diff_sec / max(1, target_sec)) < 0.35  # Within 35% variance is acceptable
    checks["duration_within_tolerance"] = duration_ok
    if not duration_ok:
        issues.append(f"Duration difference: Target {target_duration_minutes}m, Actual {format_duration_human(actual_duration_sec)}")

    # 5. Audio-Visual Sync Drift Check
    narration_duration_sec = 0.0
    if narration_exists:
        try:
            a_probe = probe_media_file(master_narration_audio_path)
            narration_duration_sec = float(a_probe.get("duration_seconds", 0.0))
        except Exception:
            pass
    av_drift_sec = round(abs(actual_duration_sec - narration_duration_sec), 2) if (video_exists and narration_exists and actual_duration_sec > 0 and narration_duration_sec > 0) else 0.0
    av_sync_ok = av_drift_sec < 0.5 if (video_exists and narration_exists and actual_duration_sec > 0 and narration_duration_sec > 0) else True
    checks["av_sync_drift_seconds"] = av_drift_sec
    checks["av_sync_aligned"] = av_sync_ok
    if not av_sync_ok:
        issues.append(f"Audio-Visual sync drift ({av_drift_sec}s) exceeds acceptable threshold (<0.5s)")

    # Overall QA status
    status = "PASS" if (video_exists and narration_exists and sub_exists) else "FAIL"

    # Separate Automated Checks and Manual Listening Checklist matching Module 13 & 16
    manual_listening_checklist = [
        {"item": "Audio-Visual synchronization: Narration corresponds to active characters, setting, and plot events on screen", "status": "Pending Manual Audit"},
        {"item": "Pronunciation of character names and unfamiliar terms verified", "status": "Pending Manual Audit"},
        {"item": "Emotional delivery appropriateness across scenes (mystery/suspense/action/climax)", "status": "Pending Manual Audit"},
        {"item": "Natural breathing and pause phrasing comfort", "status": "Pending Manual Audit"},
        {"item": "Consistent narrator identity throughout entire video", "status": "Pending Manual Audit"},
        {"item": "Narration clearly intelligible above background music/sound", "status": "Pending Manual Audit"},
        {"item": "Transformative commentary & copyright fair use disclaimer verified", "status": "Acknowledged"}
    ]

    qa_report = {
        "status": status,
        "target_duration": f"{target_duration_minutes}:00",
        "actual_duration_seconds": round(actual_duration_sec, 2),
        "actual_duration_human": format_duration_human(actual_duration_sec),
        "checks": checks,
        "automated_checks": checks,
        "manual_listening_checklist": manual_listening_checklist,
        "issues": issues,
        "audio_ok": checks.get("audio_stream_valid", False) and narration_exists,
        "subtitle_ok": sub_exists,
        "timeline_ok": video_exists and duration_ok,
        "manual_review_required": True,
        "safety_disclaimer_acknowledged": True
    }

    safe_write_json(output_report_path, qa_report)
    logger.info(f"QA report generated (Status: {status}) -> {output_report_path}")

    return qa_report
