"""Narration synthesis pipeline with segment chunking, duration measurement, and mastering."""

import os
import subprocess
import hashlib
from typing import Dict, Any, List, Optional, Union

from app.tts.base import TTSProvider
from app.tts.edge_tts_provider import EdgeTTSProvider
from app.tts.fallback_provider import FallbackTTSProvider
from app.tts.google_adapters import UnifiedVoiceAdapter, get_voice_adapter
from app.audio.post_processor import AudioPostProcessor
from app.core.logger import get_logger
from app.core.models import DeliveryProfile
from app.utils.files import safe_write_json
from app.media.probe import probe_media_file

logger = get_logger()


def fit_audio_to_duration(
    audio_path: str,
    target_duration: float,
    output_path: str,
    min_tempo: float = 0.75,
    max_tempo: float = 2.0
) -> float:
    """Stretch or compress audio to match target_duration using FFmpeg atempo."""
    if not os.path.isfile(audio_path) or target_duration <= 0:
        return target_duration

    try:
        probe = probe_media_file(audio_path)
        actual_duration = float(probe.get("duration_seconds", target_duration))
    except Exception:
        actual_duration = target_duration

    if actual_duration <= 0:
        return target_duration

    ratio = actual_duration / target_duration
    ratio = max(min_tempo, min(max_tempo, ratio))

    if ratio > 2.0:
        import math
        r1 = math.sqrt(ratio)
        r2 = ratio / r1
        atempo_filter = f"atempo={r1:.4f},atempo={r2:.4f}"
    elif ratio < 0.5:
        import math
        r1 = math.sqrt(ratio)
        r2 = ratio / r1
        atempo_filter = f"atempo={r1:.4f},atempo={r2:.4f}"
    else:
        atempo_filter = f"atempo={ratio:.4f}"

    cmd = [
        "ffmpeg", "-y",
        "-i", audio_path,
        "-filter:a", atempo_filter,
        "-ar", "44100",
        "-ac", "2",
        output_path
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return target_duration
    except Exception as e:
        logger.warning(f"Audio fit failed ({e}), using original duration")
        return actual_duration


def get_tts_provider(preferred_engine: str = "edge-tts") -> TTSProvider:
    """Legacy factory returning a TTSProvider instance for backward compatibility."""
    if preferred_engine == "edge-tts":
        try:
            prov = EdgeTTSProvider()
            if prov.is_available():
                return prov
        except Exception as e:
            logger.warning(f"EdgeTTSProvider initialization failed: {e}")

    logger.info("Falling back to System / Offline TTS Provider...")
    return FallbackTTSProvider()


def synthesize_script_narration(
    script_manifest: Dict[str, Any],
    output_dir: str,
    tts_provider: Union[TTSProvider, UnifiedVoiceAdapter, str],
    speed: float = 1.0,
    voice_id: Optional[str] = None,
    pitch: Union[int, float, str] = 0,
    sync_to_video: bool = False
) -> Dict[str, Any]:
    """Synthesize all narration segments into individual WAV files and master into full narration.

    Supports both legacy TTSProvider and modern UnifiedVoiceAdapter with per-segment isolation.
    """
    os.makedirs(output_dir, exist_ok=True)
    segments_dir = os.path.join(output_dir, "segments")
    os.makedirs(segments_dir, exist_ok=True)
    temp_dir = os.path.join(output_dir, "temp_assembly")
    os.makedirs(temp_dir, exist_ok=True)

    language = script_manifest.get("language", "en")
    narration_style = script_manifest.get("style", "cinematic_storytelling")
    segments = script_manifest.get("segments", [])
    pronunciation_dict = script_manifest.get("pronunciation_dictionary", {})

    # Resolve adapter / provider
    adapter = None
    if isinstance(tts_provider, UnifiedVoiceAdapter):
        adapter = tts_provider
        provider_name = adapter.name
    elif isinstance(tts_provider, str):
        adapter = get_voice_adapter(tts_provider)
        provider_name = adapter.name
    elif hasattr(tts_provider, "name") and tts_provider.name in ("gemini", "google_cloud"):
        adapter = get_voice_adapter(tts_provider.name)
        provider_name = adapter.name
    else:
        provider_name = getattr(tts_provider, "name", "edge-tts")

    # Determine voice ID
    if voice_id:
        voice = voice_id
    elif adapter:
        voices = adapter.list_voices(language)
        voice = voices[0]["id"] if voices else "default"
    else:
        voice = tts_provider.get_default_voice(language, narration_style)

    logger.info(
        f"Synthesizing {len(segments)} narration segments using {provider_name} "
        f"(Voice: {voice}, Pitch: {pitch}, Base Speed: {speed}x)..."
    )

    synthesized_segments = []
    segment_wav_files = []
    total_actual_sec = 0.0

    post_processor = AudioPostProcessor()

    for idx, seg in enumerate(segments):
        seg_id = seg.get("segment_id", idx + 1)
        text = seg.get("clean_text") or seg.get("narration_text", "").strip()
        if not text:
            continue

        wav_filename = f"narration_{seg_id:03d}.wav"
        wav_path = os.path.join(segments_dir, wav_filename)

        # Check existing segment audio (cache reuse for unchanged segments and pitch)
        text_hash = hashlib.sha256(f"{voice}:{text}:{speed}:{pitch}".encode("utf-8")).hexdigest()[:12]
        hash_file = os.path.join(segments_dir, f"narration_{seg_id:03d}.hash")
        is_already_done = False
        if os.path.isfile(wav_path) and os.path.isfile(hash_file) and os.path.getsize(wav_path) > 1000:
            try:
                with open(hash_file, "r", encoding="utf-8") as hf:
                    if hf.read().strip() == text_hash:
                        qc = post_processor.inspect_audio_segment(wav_path)
                        if qc["valid"]:
                            is_already_done = True
            except Exception:
                pass

        if not is_already_done:
            # Segment synthesis with retry and isolated fallback
            synthesis_success = False
            last_err = None

            for attempt in range(1, 4):
                try:
                    if adapter:
                        voice_cfg = {
                            "voice_id": voice,
                            "language": language,
                            "speed": speed,
                            "pitch": pitch
                        }
                        adapter.generate_segment(
                            segment=seg,
                            voice_config=voice_cfg,
                            output_path=wav_path,
                            pronunciation_dict=pronunciation_dict
                        )
                    else:
                        pacing = float(seg.get("pacing", 1.0)) * speed
                        tts_provider.synthesize_to_file(
                            text=text,
                            output_file_path=wav_path,
                            language=language,
                            voice_id=voice,
                            speed=pacing,
                            pitch=pitch
                        )

                    # Validate generated audio
                    qc = post_processor.inspect_audio_segment(wav_path)
                    if qc["valid"]:
                        synthesis_success = True
                        try:
                            with open(hash_file, "w", encoding="utf-8") as hf:
                                hf.write(text_hash)
                        except Exception:
                            pass
                        break
                    else:
                        last_err = f"Validation issues: {qc.get('issues')}"
                except Exception as e:
                    last_err = str(e)
                    logger.warning(f"Synthesis attempt {attempt}/3 failed for segment #{seg_id}: {e}")

            if not synthesis_success:
                logger.error(f"TTS synthesis failed for segment #{seg_id}: {last_err}. Using fallback.")
                fallback = FallbackTTSProvider()
                fallback.synthesize_to_file(text, wav_path, language=language, speed=speed)
                try:
                    with open(hash_file, "w", encoding="utf-8") as hf:
                        hf.write(text_hash)
                except Exception:
                    pass

        # Measure actual duration
        duration_sec = float(seg.get("estimated_seconds", 15.0))
        if os.path.isfile(wav_path):
            try:
                probe = probe_media_file(wav_path)
                duration_sec = float(probe.get("duration_seconds", duration_sec))
            except Exception:
                pass

        # Sync audio to target estimated duration if requested
        estimated_sec = float(seg.get("estimated_seconds", duration_sec))
        if sync_to_video and abs(duration_sec - estimated_sec) > 0.5:
            fitted_path = wav_path.replace(".wav", "_fitted.wav")
            fitted_dur = fit_audio_to_duration(
                audio_path=wav_path,
                target_duration=estimated_sec,
                output_path=fitted_path,
                min_tempo=0.80,
                max_tempo=1.80
            )
            if os.path.isfile(fitted_path):
                wav_path = fitted_path
                duration_sec = fitted_dur

        seg_data = dict(seg)
        seg_data["audio_file"] = wav_path
        seg_data["actual_duration_seconds"] = round(duration_sec, 2)
        seg_data["audio_status"] = "completed"
        synthesized_segments.append(seg_data)
        segment_wav_files.append(wav_path)
        total_actual_sec += duration_sec

    # Assemble master track with EBU R128 broadcast loudness mastering
    full_narration_path = os.path.join(output_dir, "full_narration.wav")
    mastering_result = post_processor.assemble_narration_track(
        segment_files=segment_wav_files,
        output_master_wav=full_narration_path,
        temp_dir=temp_dir,
        apply_loudnorm=True
    )

    # Export MP3 delivery format alongside master WAV
    delivery_files = post_processor.export_delivery_formats(
        master_wav=full_narration_path,
        output_base_path=os.path.join(output_dir, "master_narration")
    )

    # Save complete voice manifest
    voice_manifest = {
        "engine": provider_name,
        "language": language,
        "voice_id": voice,
        "speed": speed,
        "total_segments": len(synthesized_segments),
        "total_duration_seconds": round(mastering_result["total_duration_seconds"], 2),
        "full_narration_file": full_narration_path,
        "delivery_mp3": delivery_files["mp3"],
        "segments": synthesized_segments,
        "mastering": mastering_result
    }
    manifest_file = os.path.join(output_dir, "voice_manifest.json")
    safe_write_json(manifest_file, voice_manifest)
    logger.info(
        f"Master narration audio ready: {len(synthesized_segments)} segments "
        f"({round(mastering_result['total_duration_seconds'], 1)}s total). "
        f"Master WAV: {full_narration_path}, MP3: {delivery_files['mp3']}"
    )

    return voice_manifest


def regenerate_single_segment(
    segment_id: int,
    script_manifest: Dict[str, Any],
    output_dir: str,
    tts_provider: Union[TTSProvider, UnifiedVoiceAdapter, str],
    voice_id: Optional[str] = None
) -> Optional[str]:
    """Regenerate a single narration segment audio file without synthesizing the entire movie."""
    segments = script_manifest.get("segments", [])
    target_seg = next((s for s in segments if s.get("segment_id") == segment_id), None)
    if not target_seg:
        logger.warning(f"Segment #{segment_id} not found in script manifest.")
        return None

    segments_dir = os.path.join(output_dir, "segments")
    os.makedirs(segments_dir, exist_ok=True)
    wav_path = os.path.join(segments_dir, f"narration_{segment_id:03d}.wav")
    if os.path.exists(wav_path):
        os.remove(wav_path)

    text = target_seg.get("clean_text") or target_seg.get("narration_text", "")
    language = script_manifest.get("language", "en")
    pronunciation_dict = script_manifest.get("pronunciation_dictionary", {})

    adapter = tts_provider if isinstance(tts_provider, UnifiedVoiceAdapter) else get_voice_adapter(getattr(tts_provider, "name", "edge-tts"))
    chosen_voice = voice_id or adapter.list_voices(language)[0]["id"]

    adapter.generate_segment(
        segment=target_seg,
        voice_config={"voice_id": chosen_voice, "language": language},
        output_path=wav_path,
        pronunciation_dict=pronunciation_dict
    )
    logger.info(f"Regenerated segment #{segment_id} audio -> {wav_path}")
    return wav_path
