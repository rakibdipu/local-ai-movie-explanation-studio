"""YouTube video downloader using yt-dlp with progress reporting and quality selection."""

import os
import re
import json
import subprocess
from typing import Optional, Dict, Any, Tuple
from app.core.logger import get_logger

logger = get_logger()

# Supported YouTube / video-sharing URL patterns
_YT_PATTERNS = [
    r"(?:https?://)?(?:www\.)?youtube\.com/watch\?.*v=[\w-]+",
    r"(?:https?://)?(?:www\.)?youtu\.be/[\w-]+",
    r"(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+",
    r"(?:https?://)?(?:m\.)?youtube\.com/watch\?.*v=[\w-]+",
]


def is_youtube_url(url: str) -> bool:
    """Return True if *url* looks like a YouTube (or short-link) video URL."""
    url = url.strip()
    for pattern in _YT_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


def _yt_dlp_bin() -> str:
    """Return path to yt-dlp binary (venv-aware)."""
    # Try the venv-local binary first
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".venv", "bin", "yt-dlp"),
        "yt-dlp",  # system PATH fallback
    ]
    for c in candidates:
        c = os.path.normpath(c)
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return "yt-dlp"


def fetch_video_info(url: str) -> Dict[str, Any]:
    """Fetch video metadata without downloading.

    Returns a dict with keys:
        title, uploader, duration_seconds, resolution, filesize_approx_mb, description
    """
    bin_path = _yt_dlp_bin()
    cmd = [
        bin_path,
        "--dump-json",
        "--no-playlist",
        "--quiet",
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "yt-dlp metadata fetch failed")
        info = json.loads(result.stdout)
        return {
            "title": info.get("title", "unknown"),
            "uploader": info.get("uploader", "unknown"),
            "duration_seconds": float(info.get("duration", 0)),
            "resolution": f"{info.get('width', 0)}x{info.get('height', 0)}",
            "filesize_approx_mb": round((info.get("filesize_approx") or 0) / 1_048_576, 1),
            "description": (info.get("description") or "")[:500],
            "webpage_url": info.get("webpage_url", url),
            "id": info.get("id", ""),
        }
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse yt-dlp output: {exc}") from exc


def download_youtube_video(
    url: str,
    output_dir: str,
    max_height: int = 1080,
    prefer_format: str = "mp4",
    cookies_file: Optional[str] = None,
    show_progress: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """Download a YouTube video to *output_dir*.

    Args:
        url:            Full YouTube URL.
        output_dir:     Destination directory (created if missing).
        max_height:     Maximum vertical resolution (720 saves bandwidth; 1080 for quality).
        prefer_format:  Container preference, default "mp4".
        cookies_file:   Optional path to a Netscape cookies.txt for age-gated / member videos.
        show_progress:  Show yt-dlp progress bar in terminal.

    Returns:
        (local_file_path, video_info_dict)

    Raises:
        RuntimeError on download failure.
    """
    os.makedirs(output_dir, exist_ok=True)

    bin_path = _yt_dlp_bin()

    # Format selector: best video+audio up to max_height, merged into mp4
    fmt = (
        f"136+140/"
        f"bestvideo[height<={max_height}][ext={prefer_format}]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={max_height}]+bestaudio/"
        f"best[height<={max_height}]/"
        "best"
    )

    # Output template: sanitized title + video ID to avoid collisions
    out_template = os.path.join(output_dir, "%(title).80s [%(id)s].%(ext)s")

    cmd = [
        bin_path,
        "--no-playlist",
        "-N", "8",
        "--ignore-errors",
        "--format", fmt,
        "--merge-output-format", prefer_format,
        "--output", out_template,
        "--write-info-json",       # writes <name>.info.json alongside
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "hi-orig,hi,en,bn",
        "--convert-subs", "srt",
        "--no-overwrites",         # skip if already downloaded
    ]

    if not show_progress:
        cmd += ["--quiet", "--no-warnings"]

    if cookies_file and os.path.isfile(cookies_file):
        cmd += ["--cookies", cookies_file]

    cmd.append(url)

    logger.info(f"Downloading YouTube video: {url}")
    logger.debug(f"yt-dlp command: {' '.join(cmd)}")

    try:
        proc = subprocess.run(cmd, timeout=3600)   # 1 hour max
        if proc.returncode not in (0, 1):          # 1 = partial / already exists
            raise RuntimeError(f"yt-dlp exited with code {proc.returncode}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("YouTube download timed out after 1 hour")

    # Find the downloaded file (newest mp4/mkv/webm in output_dir matching video id if known)
    video_id = None
    m = re.search(r"[?&]v=([\w-]+)", url) or re.search(r"youtu\.be/([\w-]+)", url)
    if m:
        video_id = m.group(1)

    video_file = _find_downloaded_file(output_dir, prefer_format, video_id=video_id)
    if not video_file:
        raise RuntimeError(f"Download finished but no video file found in '{output_dir}'")

    # Read the sidecar .info.json if present
    info_json_path = video_file.rsplit(".", 1)[0] + ".info.json"
    info: Dict[str, Any] = {}
    if os.path.isfile(info_json_path):
        try:
            with open(info_json_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            info = {
                "title": raw.get("title", ""),
                "uploader": raw.get("uploader", ""),
                "duration_seconds": float(raw.get("duration", 0)),
                "resolution": f"{raw.get('width', 0)}x{raw.get('height', 0)}",
                "description": (raw.get("description") or "")[:500],
                "webpage_url": raw.get("webpage_url", url),
                "id": raw.get("id", ""),
            }
        except Exception:
            pass

    logger.info(f"Download complete: {os.path.basename(video_file)}")
    return video_file, info


def _find_downloaded_file(directory: str, prefer_ext: str = "mp4", video_id: Optional[str] = None) -> Optional[str]:
    """Return the most recently modified video file in *directory* matching video_id."""
    video_exts = {prefer_ext, "mp4", "mkv", "webm", "mov", "avi"}
    candidates = []
    for fname in os.listdir(directory):
        if video_id and f"[{video_id}]" not in fname:
            continue
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
        if ext in video_exts:
            full = os.path.join(directory, fname)
            candidates.append((os.path.getmtime(full), full))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]
