"""Timecode manipulation and conversion utilities."""

from typing import Union
import re


def seconds_to_hms(seconds: Union[int, float], delimiter: str = ":", include_millis: bool = False, decimal_sep: str = ".") -> str:
    """Convert floating point or integer seconds into HH:MM:SS or HH:MM:SS.mmm format.
    
    Args:
        seconds: Time in seconds.
        delimiter: Separator between hours, minutes, seconds (default ':').
        include_millis: Whether to include millisecond precision.
        decimal_sep: Separator before milliseconds ('.' or ',').
    """
    if seconds is None or seconds < 0:
        seconds = 0.0
    
    total_seconds = float(seconds)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = int(total_seconds % 60)
    millis = int(round((total_seconds - int(total_seconds)) * 1000))
    if millis >= 1000:
        millis = 0
        secs += 1
        if secs >= 60:
            secs = 0
            minutes += 1
            if minutes >= 60:
                minutes = 0
                hours += 1

    if include_millis:
        return f"{hours:02d}{delimiter}{minutes:02d}{delimiter}{secs:02d}{decimal_sep}{millis:03d}"
    return f"{hours:02d}{delimiter}{minutes:02d}{delimiter}{secs:02d}"


def seconds_to_srt_time(seconds: Union[int, float]) -> str:
    """Convert seconds to SRT timestamp format: 00:01:23,456"""
    return seconds_to_hms(seconds, delimiter=":", include_millis=True, decimal_sep=",")


def seconds_to_vtt_time(seconds: Union[int, float]) -> str:
    """Convert seconds to VTT timestamp format: 00:01:23.456"""
    return seconds_to_hms(seconds, delimiter=":", include_millis=True, decimal_sep=".")


def seconds_to_ass_time(seconds: Union[int, float]) -> str:
    """Convert seconds to ASS/SSA timestamp format: H:MM:SS.cc (centiseconds)"""
    if seconds is None or seconds < 0:
        seconds = 0.0
    total_seconds = float(seconds)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    secs = int(total_seconds % 60)
    centis = int(round((total_seconds - int(total_seconds)) * 100))
    if centis >= 100:
        centis = 0
        secs += 1
        if secs >= 60:
            secs = 0
            minutes += 1
            if minutes >= 60:
                minutes = 0
                hours += 1
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def parse_time_to_seconds(timestr: Union[str, int, float]) -> float:
    """Parse various timestamp string representations into float seconds.
    
    Supported formats:
    - "01:23:45.678" or "01:23:45,678"
    - "23:45.678"
    - "45.678" or 45.678
    - "1h 20m 15s", "20m", "90s"
    """
    if isinstance(timestr, (int, float)):
        return max(0.0, float(timestr))
    
    if not isinstance(timestr, str):
        return 0.0
    
    text = timestr.strip()
    if not text:
        return 0.0

    # Human formats: "20m", "1h 30m", "45s", "10 min", "15 মিনিট", "10 मिनट"
    if re.search(r"(?:[hms]|hour|min|sec|ঘন্টা|মিনিট|সেকেন্ড|घंटे|मिनट|सेकंड)", text, re.IGNORECASE):
        total = 0.0
        h_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:h\b|hr\b|hours?|ঘন্টা|घंटे)", text, re.I)
        m_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m\b|min\b|mins?|minutes?|মিনিট|मिनट)", text, re.I)
        s_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:s\b|sec\b|seconds?|সেকেন্ড|सेकंड)", text, re.I)
        if h_match:
            total += float(h_match.group(1)) * 3600
        if m_match:
            total += float(m_match.group(1)) * 60
        if s_match:
            total += float(s_match.group(1))
        if total > 0:
            return total

    # Normalize comma to period
    text = text.replace(",", ".")
    
    # HH:MM:SS.mmm or MM:SS.mmm
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        elif len(parts) == 1:
            return float(parts[0])
    except ValueError:
        pass
    
    return 0.0


def format_duration_human(seconds: Union[int, float]) -> str:
    """Format duration into human readable string like '19m 42s' or '1h 22m 10s'."""
    sec = int(round(seconds))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"
