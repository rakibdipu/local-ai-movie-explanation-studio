"""Multi-language YouTube audio track generator and muxer.

Produces a single MP4 with multiple audio streams so YouTube viewers can
switch between Bangla, Hindi, and English using the audio track selector.
Also exports individual .aac files for manual YouTube Studio upload.
"""

import os
import subprocess
from typing import List, Dict, Any, Optional
from app.core.logger import get_logger
from app.media.probe import probe_media_file
from app.utils.files import safe_write_json

logger = get_logger()

# ISO 639-2 language codes for FFmpeg metadata
_LANG_ISO = {"bn": "ben", "hi": "hin", "en": "eng"}
_LANG_DISPLAY = {"bn": "বাংলা (Bangla)", "hi": "हिंदी (Hindi)", "en": "English"}


def export_audio_track(
    narration_wav: str,
    output_aac: str,
    language: str,
    bitrate: str = "192k"
) -> str:
    """Convert a narration WAV to a standalone AAC file for YouTube Studio upload."""
    os.makedirs(os.path.dirname(os.path.abspath(output_aac)), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", narration_wav,
        "-c:a", "aac",
        "-b:a", bitrate,
        "-metadata", f"language={_LANG_ISO.get(language, language)}",
        "-metadata", f"title={_LANG_DISPLAY.get(language, language)}",
        output_aac
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    logger.info(f"Exported audio track [{language.upper()}] → {output_aac}")
    return output_aac


def build_multilang_video(
    single_lang_video: str,
    language_audio_map: Dict[str, str],   # {lang_code: narration_wav_path}
    output_path: str,
    primary_language: str = "bn",
    video_duration: Optional[float] = None,
    preset: str = "faster",
    crf: int = 22
) -> str:
    """Mux multiple narration audio tracks into one MP4.

    The resulting video has:
      - One video stream (copied from single_lang_video)
      - One audio stream per language, each tagged with ISO language metadata
    YouTube will detect these tracks and show a language selector to viewers.

    Args:
        single_lang_video: Path to the rendered video (with primary audio already in it).
        language_audio_map: Dict mapping language code → narration WAV/AAC path.
        output_path: Where to write the multi-track MP4.
        primary_language: The language whose audio is already in single_lang_video.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Sort so primary language is audio track 0
    langs = sorted(language_audio_map.keys(), key=lambda l: (0 if l == primary_language else 1))
    lang_paths = [language_audio_map[l] for l in langs]

    # Build FFmpeg command: -i video, then -i audio per language
    cmd = ["ffmpeg", "-y", "-i", single_lang_video]
    for ap in lang_paths:
        cmd += ["-i", ap]

    # Map video from first input, audio from each subsequent input
    cmd += ["-map", "0:v:0"]
    for i in range(len(langs)):
        cmd += ["-map", f"{i + 1}:a:0"]

    # Codec settings
    cmd += [
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
    ]

    # Language metadata per audio stream
    for i, lang in enumerate(langs):
        iso = _LANG_ISO.get(lang, lang)
        display = _LANG_DISPLAY.get(lang, lang)
        cmd += [
            f"-metadata:s:a:{i}", f"language={iso}",
            f"-metadata:s:a:{i}", f"title={display}",
        ]

    # Shortest flag — trim to shortest track (prevents silence at end)
    cmd += ["-shortest", output_path]

    logger.info(f"Muxing multi-language video with tracks: {langs}")
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        logger.info(f"Multi-language video ready → {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"Multi-language mux failed: {e}. Falling back to single-language video.")
        return single_lang_video


def generate_multilang_subtitles_package(
    lang_srt_map: Dict[str, str],   # {lang_code: srt_path}
    output_dir: str
) -> Dict[str, str]:
    """Copy and rename SRT files into YouTube-ready subtitle package.

    YouTube accepts SRT files named with language codes for bulk upload.
    Returns dict of {lang_code: output_srt_path}.
    """
    os.makedirs(output_dir, exist_ok=True)
    result = {}
    for lang, src_srt in lang_srt_map.items():
        if os.path.isfile(src_srt):
            iso = _LANG_ISO.get(lang, lang)
            dest = os.path.join(output_dir, f"subtitles_{lang}_{iso}.srt")
            with open(src_srt, "r", encoding="utf-8") as f:
                content = f.read()
            with open(dest, "w", encoding="utf-8") as f:
                f.write(content)
            result[lang] = dest
            logger.info(f"Subtitle package [{lang.upper()}] → {dest}")
    return result


def write_youtube_upload_guide(
    output_dir: str,
    multilang_video: str,
    individual_audio_map: Dict[str, str],   # {lang_code: aac_path}
    subtitle_map: Dict[str, str],
    primary_language: str,
    movie_title: str = "Movie Explanation"
) -> str:
    """Write a plain-text step-by-step YouTube Studio upload guide."""

    lang_names = {
        "bn": "বাংলা (Bangla)",
        "hi": "हिंदी (Hindi)",
        "en": "English"
    }

    lines = [
        "=" * 65,
        " YOUTUBE UPLOAD GUIDE — Multi-Language Movie Explanation",
        "=" * 65,
        "",
        f"Video title suggestion: {movie_title} | Full Explanation",
        "",
        "── STEP 1: Upload main video ───────────────────────────────",
        f"  File: {os.path.basename(multilang_video)}",
        "  This file contains ALL language audio tracks embedded.",
        "  YouTube will automatically detect and offer them to viewers.",
        "",
        "── STEP 2: Add dubbed audio tracks (YouTube Studio) ────────",
        "  Go to: YouTube Studio → Videos → Edit → Audio Tracks",
        "  Upload each file below separately and set its language:",
    ]
    for lang, path in individual_audio_map.items():
        lines.append(f"    [{lang.upper()}] {lang_names.get(lang, lang)}")
        lines.append(f"         File: {os.path.basename(path)}")
    lines += [
        "",
        "── STEP 3: Add subtitles ───────────────────────────────────",
        "  Go to: YouTube Studio → Videos → Edit → Subtitles → Add",
    ]
    for lang, path in subtitle_map.items():
        lines.append(f"    [{lang.upper()}] {lang_names.get(lang, lang)}")
        lines.append(f"         File: {os.path.basename(path)}")
    lines += [
        "",
        "── STEP 4: Set default audio track ────────────────────────",
        f"  Set primary language to: {lang_names.get(primary_language, primary_language)}",
        "  Viewers can switch languages using the ⚙ gear icon on YouTube.",
        "",
        "── STEP 5: Recommended tags ────────────────────────────────",
        "  #MovieExplanation #MovieSummary #বাংলাMovie #হিন্দিMovie",
        "  #MovieExplained #FilmSummary #সিনেমাব্যাখ্যা",
        "",
        "=" * 65,
        "Generated by AI Movie Explanation Studio",
        "=" * 65,
    ]

    guide_path = os.path.join(output_dir, "youtube_upload_guide.txt")
    with open(guide_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"YouTube upload guide written → {guide_path}")
    return guide_path


def run_multilang_export(
    primary_video_path: str,
    primary_language: str,
    language_narration_map: Dict[str, str],  # {lang_code: full_narration.wav}
    language_srt_map: Dict[str, str],        # {lang_code: final.srt}
    output_dir: str,
    movie_title: str = "Movie Explanation",
    preset: str = "faster",
    crf: int = 22
) -> Dict[str, Any]:
    """Full multi-language YouTube export pipeline.

    Returns a manifest dict with all output file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    audio_dir = os.path.join(output_dir, "audio_tracks")
    subs_dir = os.path.join(output_dir, "subtitles")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(subs_dir, exist_ok=True)

    # 1. Export individual audio tracks (.aac) for YouTube Studio
    individual_audio = {}
    for lang, wav_path in language_narration_map.items():
        if os.path.isfile(wav_path):
            aac_out = os.path.join(audio_dir, f"audio_{lang}.aac")
            try:
                export_audio_track(wav_path, aac_out, lang)
                individual_audio[lang] = aac_out
            except Exception as e:
                logger.warning(f"Audio track export failed for [{lang}]: {e}")

    # 2. Build multi-track MP4
    multilang_video_path = os.path.join(output_dir, "final_multilang.mp4")
    actual_video = build_multilang_video(
        single_lang_video=primary_video_path,
        language_audio_map=language_narration_map,
        output_path=multilang_video_path,
        primary_language=primary_language,
        preset=preset,
        crf=crf
    )

    # 3. Package subtitles
    packaged_subs = generate_multilang_subtitles_package(language_srt_map, subs_dir)

    # 4. Write YouTube guide
    guide_path = write_youtube_upload_guide(
        output_dir=output_dir,
        multilang_video=actual_video,
        individual_audio_map=individual_audio,
        subtitle_map=packaged_subs,
        primary_language=primary_language,
        movie_title=movie_title
    )

    manifest = {
        "multilang_video": actual_video,
        "audio_tracks": individual_audio,
        "subtitles": packaged_subs,
        "youtube_guide": guide_path,
        "languages": list(language_narration_map.keys()),
        "primary_language": primary_language
    }

    safe_write_json(os.path.join(output_dir, "multilang_manifest.json"), manifest)
    return manifest
