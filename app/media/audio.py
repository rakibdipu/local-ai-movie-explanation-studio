"""Audio extraction and CPU-optimized Speech-to-Text transcription."""

import os
import subprocess
from typing import List, Dict, Any, Optional
from app.core.logger import get_logger

logger = get_logger()


def extract_mono_speech_audio(movie_path: str, output_wav_path: str, audio_stream_idx: Optional[int] = None) -> str:
    """Extract primary dialogue track to 16kHz mono WAV for transcription.
    
    Optimized for low-RAM streaming extraction with FFmpeg.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)
    
    map_arg = f"0:{audio_stream_idx}" if audio_stream_idx is not None else "0:a:0"
    cmd = [
        "ffmpeg",
        "-y",
        "-i", movie_path,
        "-map", map_arg,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        output_wav_path
    ]

    logger.info(f"Extracting speech audio track from {os.path.basename(movie_path)}...")
    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if not os.path.isfile(output_wav_path) or os.path.getsize(output_wav_path) == 0:
            raise RuntimeError("Audio extraction produced empty file.")
        return output_wav_path
    except Exception as e:
        logger.error(f"FFmpeg audio extraction failed: {e}")
        raise


def transcribe_audio_whisper(
    wav_path: str,
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
    threads: int = 2
) -> List[Dict[str, Any]]:
    """Transcribe audio using faster-whisper on CPU with INT8 quantization."""
    if not os.path.isfile(wav_path):
        raise FileNotFoundError(f"Audio file not found: {wav_path}")

    logger.info(f"Transcribing audio with faster-whisper (model={model_size}, device={device}, compute_type={compute_type})...")
    
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_size, device=device, compute_type=compute_type, cpu_threads=threads)
        segments, info = model.transcribe(wav_path, beam_size=5, word_timestamps=False, vad_filter=True)

        cues: List[Dict[str, Any]] = []
        cue_id = 1
        for seg in segments:
            text = seg.text.strip()
            if text:
                cues.append({
                    "id": cue_id,
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "duration": round(seg.end - seg.start, 2),
                    "text": text
                })
                cue_id += 1

        logger.info(f"Transcription complete: {len(cues)} dialogue segments detected (detected language: {info.language}).")
        return cues
    except Exception as e:
        logger.error(f"Faster-whisper transcription error: {e}")
        raise
