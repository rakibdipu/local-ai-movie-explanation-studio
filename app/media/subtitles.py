"""Subtitle-first extraction, parsing, normalization, and narrative chunking."""

import os
import re
import subprocess
import glob
from typing import List, Dict, Any, Optional, Tuple
import pysrt
import webvtt
from app.core.logger import get_logger
from app.utils.timecode import parse_time_to_seconds, seconds_to_srt_time
from app.utils.files import safe_write_json

logger = get_logger()


def clean_subtitle_text(text: str) -> str:
    """Clean subtitle string by stripping HTML tags, ASS override tags, and HI captions.
    
    Removes:
    - HTML formatting tags (<i>, <b>, <font>, </u>, etc.)
    - ASS override codes ({\\an8}, {\\pos(x,y)}, etc.)
    - Hearing impaired / sound effect descriptions ([Laughter], (Sighs), [GUNSHOT], etc.)
    - Multiple redundant spaces and newlines
    """
    if not text:
        return ""

    # Strip ASS style curly-brace tags
    text = re.sub(r"\{[^}]*\}", "", text)

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Strip Hearing-Impaired markers like [MUSIC PLAYING], (DOOR OPENS), [संगीत], etc.
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\([^\)]*\)", "", text)

    # Strip music notes and anything enclosed in music notes (e.g. ♪ song lyrics ♪ or # song lyrics #)
    text = re.sub(r"[♪♫#][^♪♫#\r\n]*[♪♫#]", "", text)
    text = re.sub(r"[♪♫#]+", "", text)

    # Replace speaker prefixes like "JOHN:" or "- JOHN:" with "- "
    text = re.sub(r"^[A-Z0-9_\-\s]{2,20}:\s*", "", text, flags=re.MULTILINE)

    # Replace newlines with space
    text = re.sub(r"[\r\n]+", " ", text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def find_sidecar_subtitles(movie_path: str) -> List[str]:
    """Find external subtitle files matching movie filename."""
    base_dir = os.path.dirname(os.path.abspath(movie_path))
    movie_name, _ = os.path.splitext(os.path.basename(movie_path))
    
    sub_exts = {".srt", ".vtt", ".ass", ".ssa", ".sub"}
    found = []

    if not os.path.isdir(base_dir):
        return []

    for fname in os.listdir(base_dir):
        if fname.startswith(movie_name):
            _, ext = os.path.splitext(fname)
            if ext.lower() in sub_exts:
                full_path = os.path.join(base_dir, fname)
                if os.path.isfile(full_path):
                    found.append(full_path)

    def _sub_priority(p: str) -> Tuple[int, int, str]:
        is_orig = 1 if "-orig." in os.path.basename(p) else 0
        ext_priority = 0 if p.endswith(".srt") else (1 if p.endswith(".vtt") else 2)
        return (is_orig, ext_priority, p)

    return sorted(list(set(found)), key=_sub_priority)



def extract_embedded_subtitles(movie_path: str, output_dir: str, probe_info: Dict[str, Any]) -> List[str]:
    """Extract embedded subtitle streams from movie container into individual SRT files."""
    os.makedirs(output_dir, exist_ok=True)
    extracted_files = []
    
    sub_streams = probe_info.get("subtitles", {}).get("streams", [])
    if not sub_streams:
        return extracted_files

    for i, sub in enumerate(sub_streams):
        stream_idx = sub.get("index")
        lang = sub.get("language", f"sub_{i}")
        out_file = os.path.join(output_dir, f"track_{i}_{lang}.srt")

        cmd = [
            "ffmpeg",
            "-y",
            "-i", movie_path,
            "-map", f"0:{stream_idx}",
            out_file
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            if os.path.isfile(out_file) and os.path.getsize(out_file) > 100:
                extracted_files.append(out_file)
                logger.info(f"Extracted embedded subtitle track {stream_idx} ({lang}) -> {out_file}")
        except Exception as e:
            logger.warning(f"Failed to extract subtitle track {stream_idx}: {e}")

    return extracted_files


def parse_subtitle_file(file_path: str) -> List[Dict[str, Any]]:
    """Parse SRT, VTT, or ASS subtitle file into list of normalized cue dictionaries."""
    if not os.path.isfile(file_path):
        return []

    cues: List[Dict[str, Any]] = []
    _, ext = os.path.splitext(file_path.lower())

    try:
        if ext == ".vtt":
            vtt_obj = webvtt.read(file_path)
            for idx, caption in enumerate(vtt_obj):
                cleaned = clean_subtitle_text(caption.text)
                if cleaned:
                    start_sec = parse_time_to_seconds(caption.start)
                    end_sec = parse_time_to_seconds(caption.end)
                    if end_sec > start_sec:
                        cues.append({
                            "id": idx + 1,
                            "start": round(start_sec, 2),
                            "end": round(end_sec, 2),
                            "duration": round(end_sec - start_sec, 2),
                            "text": cleaned
                        })
        else:
            # Try pysrt for .srt, .ass, and other text formats
            subs = pysrt.open(file_path, encoding="utf-8")
            for idx, sub in enumerate(subs):
                cleaned = clean_subtitle_text(sub.text)
                if cleaned:
                    start_sec = (sub.start.hours * 3600 + sub.start.minutes * 60 +
                                 sub.start.seconds + sub.start.milliseconds / 1000.0)
                    end_sec = (sub.end.hours * 3600 + sub.end.minutes * 60 +
                               sub.end.seconds + sub.end.milliseconds / 1000.0)
                    if end_sec > start_sec:
                        cues.append({
                            "id": idx + 1,
                            "start": round(start_sec, 2),
                            "end": round(end_sec, 2),
                            "duration": round(end_sec - start_sec, 2),
                            "text": cleaned
                        })
    except Exception as e:
        logger.warning(f"Subtitle parser error on {file_path} with standard parser ({e}), attempting regex fallback...")
        cues = _fallback_srt_parser(file_path)

    return cues


def _fallback_srt_parser(file_path: str) -> List[Dict[str, Any]]:
    """Robust fallback regex parser for poorly formatted SRT files."""
    cues = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Match SRT blocks: ID \n 00:00:00,000 --> 00:00:00,000 \n Text
        pattern = re.compile(
            r"(\d+)\s*\n"
            r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*\n"
            r"([\s\S]*?)(?=\n\s*\n\d+\s*\n|\Z)",
            re.MULTILINE
        )
        for idx, match in enumerate(pattern.finditer(content)):
            _, start_str, end_str, raw_text = match.groups()
            cleaned = clean_subtitle_text(raw_text)
            if cleaned:
                start_sec = parse_time_to_seconds(start_str)
                end_sec = parse_time_to_seconds(end_str)
                if end_sec > start_sec:
                    cues.append({
                        "id": idx + 1,
                        "start": round(start_sec, 2),
                        "end": round(end_sec, 2),
                        "duration": round(end_sec - start_sec, 2),
                        "text": cleaned
                    })
    except Exception as e:
        logger.error(f"Fallback subtitle parser failed: {e}")

    return cues


def normalize_subtitles(cues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate consecutive cues, merge rapid fragments, and re-index."""
    if not cues:
        return []

    # Sort strictly by start time
    cues = sorted(cues, key=lambda x: x["start"])
    normalized: List[Dict[str, Any]] = []

    last_text = ""
    for cue in cues:
        text = cue["text"].strip()
        if not text:
            continue
        # Avoid exact duplicate consecutive dialogue
        if text.lower() == last_text.lower():
            if normalized:
                # Extend previous cue end time
                normalized[-1]["end"] = max(normalized[-1]["end"], cue["end"])
                normalized[-1]["duration"] = round(normalized[-1]["end"] - normalized[-1]["start"], 2)
            continue

        normalized.append({
            "id": len(normalized) + 1,
            "start": cue["start"],
            "end": cue["end"],
            "duration": cue["duration"],
            "text": text
        })
        last_text = text

    return normalized


def create_chunks_from_timeline(
    cues: List[Dict[str, Any]],
    total_duration: float,
    chunk_duration_sec: float = 300.0,
    overlap_sec: float = 35.0
) -> List[Dict[str, Any]]:
    """Group normalized dialogue timeline into 3-8 minute story chunks with narrative overlap."""
    if not cues:
        # If no dialogue, generate time-based chunks across the entire duration
        chunks = []
        cur_start = 0.0
        chunk_id = 1
        while cur_start < total_duration:
            cur_end = min(total_duration, cur_start + chunk_duration_sec)
            chunks.append({
                "chunk_id": chunk_id,
                "start": round(cur_start, 2),
                "end": round(cur_end, 2),
                "duration": round(cur_end - cur_start, 2),
                "dialogue_count": 0,
                "cues": [],
                "transcript": "(Visual sequence / No dialogue in this segment)"
            })
            chunk_id += 1
            cur_start += (chunk_duration_sec - overlap_sec)
            if cur_start >= total_duration - 10:
                break
        return chunks

    chunks = []
    chunk_id = 1
    cur_start = 0.0

    while cur_start < total_duration:
        cur_end = min(total_duration, cur_start + chunk_duration_sec)
        
        # Collect cues inside [cur_start, cur_end]
        segment_cues = [
            c for c in cues
            if (c["start"] >= cur_start and c["start"] < cur_end) or
               (c["end"] > cur_start and c["end"] <= cur_end) or
               (c["start"] <= cur_start and c["end"] >= cur_end)
        ]

        transcript_lines = [f"[{seconds_to_srt_time(c['start'])}] {c['text']}" for c in segment_cues]
        transcript_text = "\n".join(transcript_lines) if transcript_lines else "(Instrumental / silent sequence)"

        chunks.append({
            "chunk_id": chunk_id,
            "start": round(cur_start, 2),
            "end": round(cur_end, 2),
            "duration": round(cur_end - cur_start, 2),
            "dialogue_count": len(segment_cues),
            "cues": segment_cues,
            "transcript": transcript_text
        })

        chunk_id += 1
        cur_start += (chunk_duration_sec - overlap_sec)
        if cur_start >= total_duration - 10:
            break

    return chunks
