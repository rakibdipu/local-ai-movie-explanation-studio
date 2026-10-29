"""Audio Post-Processing, Quality Control, and Mastering Engine."""

import os
import json
import math
import subprocess
from typing import Dict, Any, List, Optional, Tuple

from app.core.logger import get_logger
from app.utils.files import safe_write_json
from app.media.probe import probe_media_file

logger = get_logger()


class AudioPostProcessor:
    """Performs acoustic validation, loudness normalization, seamless concatenation, and BGM mixing."""

    def __init__(self, target_sample_rate: int = 44100, target_channels: int = 2):
        self.target_sample_rate = target_sample_rate
        self.target_channels = target_channels

    def inspect_audio_segment(self, audio_path: str, expected_min_duration: float = 1.0) -> Dict[str, Any]:
        """Perform granular QC on an individual narration audio segment."""
        if not os.path.isfile(audio_path):
            return {
                "valid": False,
                "error": "File does not exist",
                "duration": 0.0,
                "issues": ["missing_file"]
            }

        file_size = os.path.getsize(audio_path)
        if file_size < 1000:
            return {
                "valid": False,
                "error": f"File too small ({file_size} bytes)",
                "duration": 0.0,
                "issues": ["empty_or_corrupt_file"]
            }

        issues = []
        try:
            probe = probe_media_file(audio_path)
            duration = float(probe.get("duration_seconds", 0.0))
            audio_info = probe.get("audio", {})
            channels = int(audio_info.get("channels", 1))
            sample_rate = int(audio_info.get("sample_rate", 44100))

            if duration < expected_min_duration:
                issues.append("unexpectedly_short_segment")

            # Check peak loudness and silence using FFmpeg astats / silencedetect
            cmd_stats = [
                "ffmpeg", "-i", audio_path,
                "-af", "astats=metadata=1:reset=1",
                "-f", "null", "-"
            ]
            res = subprocess.run(cmd_stats, stderr=subprocess.PIPE, text=True)
            stats_output = res.stderr

            # Detect clipping (Peak dB near or above 0 dBFS)
            clipping_detected = False
            if "Peak level dB: 0.0" in stats_output or "Peak level dB: -0.0" in stats_output:
                clipping_detected = True
                issues.append("potential_clipping")

            return {
                "valid": len(issues) == 0 or (len(issues) == 1 and issues[0] == "potential_clipping"),
                "duration": duration,
                "sample_rate": sample_rate,
                "channels": channels,
                "clipping_detected": clipping_detected,
                "issues": issues,
                "size_bytes": file_size
            }
        except Exception as exc:
            return {
                "valid": False,
                "error": str(exc),
                "duration": 0.0,
                "issues": ["probe_failed"]
            }

    def standardize_audio_segment(self, input_path: str, output_path: str) -> str:
        """Convert any audio file to 44.1kHz 16-bit Stereo PCM WAV."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-ar", str(self.target_sample_rate),
            "-ac", str(self.target_channels),
            "-acodec", "pcm_s16le",
            output_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_path

    def assemble_narration_track(
        self,
        segment_files: List[str],
        output_master_wav: str,
        temp_dir: str,
        apply_loudnorm: bool = True
    ) -> Dict[str, Any]:
        """Concatenate all segments seamlessly with loudness normalization (EBU R128)."""
        os.makedirs(os.path.dirname(os.path.abspath(output_master_wav)), exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)

        if not segment_files:
            raise ValueError("No segment audio files provided for assembly.")

        # 1. Standardize all segments to temp standardized WAVs
        standardized_files = []
        concat_lines = []
        total_duration = 0.0

        for idx, seg_file in enumerate(segment_files):
            std_path = os.path.join(temp_dir, f"std_seg_{idx+1:04d}.wav")
            self.standardize_audio_segment(seg_file, std_path)
            standardized_files.append(std_path)
            concat_lines.append(f"file '{os.path.abspath(std_path)}'")
            
            try:
                probe = probe_media_file(std_path)
                total_duration += float(probe.get("duration_seconds", 0.0))
            except Exception:
                pass

        # Write concat list
        concat_list_path = os.path.join(temp_dir, "master_concat_list.txt")
        with open(concat_list_path, "w", encoding="utf-8") as f:
            f.write("\n".join(concat_lines))

        raw_assembled_wav = os.path.join(temp_dir, "raw_assembled_narration.wav")

        # Concat standardized WAV files
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            raw_assembled_wav
        ]
        try:
            subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except Exception:
            # Fallback to re-encoding concat
            cmd_concat_reencode = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-ar", str(self.target_sample_rate),
                "-ac", str(self.target_channels),
                "-acodec", "pcm_s16le",
                raw_assembled_wav
            ]
            subprocess.run(cmd_concat_reencode, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        # 2. Master with EBU R128 Loudness Normalization & subtle warmth filter
        if apply_loudnorm:
            logger.info("Applying EBU R128 Broadcast Loudness Normalization (-16 LUFS)...")
            tmp_master_wav = output_master_wav + ".tmp.wav"
            cmd_master = [
                "ffmpeg", "-y",
                "-i", raw_assembled_wav,
                "-af", "bass=g=2.5:f=150,equalizer=f=220:width_type=q:width=1.2:g=2.0,treble=g=-0.5:f=4000,loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ar", str(self.target_sample_rate),
                "-ac", str(self.target_channels),
                tmp_master_wav
            ]
            try:
                subprocess.run(cmd_master, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                if os.path.exists(output_master_wav):
                    os.remove(output_master_wav)
                os.replace(tmp_master_wav, output_master_wav)
            except Exception as e:
                logger.warning(f"Loudnorm mastering failed ({e}), using raw assembled track.")
                if os.path.exists(tmp_master_wav):
                    os.remove(tmp_master_wav)
                if os.path.exists(output_master_wav):
                    os.remove(output_master_wav)
                os.replace(raw_assembled_wav, output_master_wav)
        else:
            if os.path.exists(output_master_wav):
                os.remove(output_master_wav)
            os.replace(raw_assembled_wav, output_master_wav)

        actual_probe = probe_media_file(output_master_wav)
        actual_dur = float(actual_probe.get("duration_seconds", total_duration))

        return {
            "master_wav": output_master_wav,
            "total_segments": len(segment_files),
            "total_duration_seconds": round(actual_dur, 2),
            "sample_rate": self.target_sample_rate,
            "channels": self.target_channels,
            "format": "pcm_s16le"
        }

    def mix_background_music_with_ducking(
        self,
        narration_wav: str,
        bgm_music_file: str,
        output_mixed_wav: str,
        bgm_volume: float = 0.08,
        ducking_attenuation_db: float = -18.0
    ) -> str:
        """Mix background music underneath narration with automatic speech sidechain ducking."""
        if not os.path.isfile(bgm_music_file):
            logger.warning(f"BGM file not found: {bgm_music_file}. Using dry narration.")
            return narration_wav

        os.makedirs(os.path.dirname(os.path.abspath(output_mixed_wav)), exist_ok=True)

        # FFmpeg sidechaincompress filter ducks music whenever voice speaks
        filter_complex = (
            f"[1:a]volume={bgm_volume},aloop=loop=-1:size=2e+09[bgm];"
            f"[bgm][0:a]sidechaincompress=threshold=0.08:ratio=6:attack=20:release=350[ducked_bgm];"
            f"[0:a][ducked_bgm]amix=inputs=2:duration=first:dropout_transition=2[out]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", narration_wav,
            "-i", bgm_music_file,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-ar", str(self.target_sample_rate),
            "-ac", str(self.target_channels),
            output_mixed_wav
        ]

        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            logger.info(f"Mixed background music with sidechain ducking -> {output_mixed_wav}")
            return output_mixed_wav
        except Exception as e:
            logger.warning(f"BGM sidechain ducking mixing failed: {e}. Returning clean narration.")
            return narration_wav

    def export_delivery_formats(self, master_wav: str, output_base_path: str) -> Dict[str, str]:
        """Export master audio into WAV and high-bitrate MP3 delivery formats."""
        wav_out = f"{output_base_path}.wav" if not output_base_path.endswith(".wav") else output_base_path
        mp3_out = f"{os.path.splitext(output_base_path)[0]}.mp3"

        # 1. WAV
        if master_wav != wav_out:
            subprocess.run(["ffmpeg", "-y", "-i", master_wav, "-c", "copy", wav_out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        # 2. MP3
        cmd_mp3 = [
            "ffmpeg", "-y",
            "-i", master_wav,
            "-codec:a", "libmp3lame",
            "-b:a", "256k",
            mp3_out
        ]
        subprocess.run(cmd_mp3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        return {
            "wav": wav_out,
            "mp3": mp3_out
        }
