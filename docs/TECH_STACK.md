# Local AI Movie Explanation Studio - Technical Stack Documentation

This document outlines the architectural choices, open-source projects, and fallback strategies selected for the **Local AI Movie Explanation Studio** running on low-resource Ubuntu Linux (8 GB RAM, CPU-first operation).

---

## 1. Core Processing & Video Pipeline

### FFmpeg / FFprobe (Static Build)
* **GitHub / Official URL**: [https://ffmpeg.org](https://ffmpeg.org) / [https://johnvansickle.com/ffmpeg/](https://johnvansickle.com/ffmpeg/)
* **Purpose**: Video demuxing, audio extraction (16kHz mono), stream inspection, selective keyframe extraction, subtitle burn-in, audio ducking, fast stream concat, and final x264 video rendering.
* **License**: LGPL 2.1+ / GPL 3.0+
* **Why Selected**: Universal industry standard for high-performance, low-memory multimedia manipulation. Uses streaming and chunked processing without buffering entire videos in RAM.
* **Fallback Option**: Pure Python OpenCV / PyAV for frame decoding if FFmpeg binary is missing.

### PySceneDetect
* **GitHub URL**: [https://github.com/Breakthrough/PySceneDetect](https://github.com/Breakthrough/PySceneDetect)
* **Purpose**: Fast cut and scene boundary detection to segment movies into visually coherent shots.
* **License**: BSD 3-Clause
* **Why Selected**: Lightweight, CPU-optimized algorithms (ContentDetector, AdaptiveDetector, ThresholdDetector) that run efficiently on 8GB RAM systems.
* **Fallback Option**: FFmpeg internal scene filter (`select='gt(scene,0.35)'`) or uniform sliding window slicing.

---

## 2. Speech-to-Text (STT) & Subtitle Engine

### PySRT & WebVTT-Py
* **GitHub URL**: [https://github.com/byroot/pysrt](https://github.com/byroot/pysrt) & [https://github.com/glut23/webvtt-py](https://github.com/glut23/webvtt-py)
* **Purpose**: Subtitle extraction, parsing, cleaning, and normalization from SRT, VTT, and ASS formats.
* **License**: MIT
* **Why Selected**: Zero-memory overhead, robust parsing of diverse formatting tags, timing synchronization, and hearing-impaired caption stripping.
* **Fallback Option**: Built-in regex-based subtitle parser.

### Faster-Whisper (CTranslate2)
* **GitHub URL**: [https://github.com/SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper)
* **Purpose**: Fallback automatic speech recognition when movies have no subtitle tracks.
* **License**: MIT
* **Why Selected**: Up to 4x faster than vanilla Whisper with less than half the memory consumption via CTranslate2 INT8 quantization on CPU. Operates well under 2GB RAM for `tiny` and `base` models.
* **Fallback Option**: OpenAI Whisper or pre-extracted subtitle requirement.

---

## 3. Text-to-Speech (TTS) Architecture

### Pluggable TTS Interface
The system implements a unified `TTSProvider` abstract base class supporting multiple engines with automatic graceful degradation:

1. **Edge-TTS**
   * **GitHub URL**: [https://github.com/rany2/edge-tts](https://github.com/rany2/edge-tts)
   * **Purpose**: High-quality natural neural voice synthesis for English, Bengali (`bn-BD-PradeepNeural`, `bn-BD-NabanitaNeural`, `bn-IN-BashkarNeural`), and Hindi (`hi-IN-MadhurNeural`, `hi-IN-SwaraNeural`).
   * **License**: GNU LGPL v3.0
   * **Why Selected**: Extremely natural prosody, human-like cadence, zero local GPU/RAM requirement, rapid synthesis.
   * **Fallback Option**: Kokoro-ONNX / Piper.

2. **Kokoro-ONNX**
   * **GitHub URL**: [https://github.com/thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) & [https://github.com/hexgrad/kokoro](https://github.com/hexgrad/kokoro)
   * **Purpose**: Local offline neural TTS engine with 82M parameters running on CPU via ONNX Runtime.
   * **License**: Apache 2.0
   * **Why Selected**: Highly expressive English prosody without robotic rhythm.

3. **Piper TTS**
   * **GitHub URL**: [https://github.com/rhasspy/piper](https://github.com/rhasspy/piper)
   * **Purpose**: Ultra-fast, lightweight local neural TTS for offline execution.
   * **License**: MIT
   * **Why Selected**: Extremely fast on low-power CPUs.

4. **System TTS Fallback**
   * **Purpose**: eSpeak-NG / pyttsx3 fallback if internet or ONNX models are unavailable.
   * **License**: GPL v3+ / MIT

---

## 4. AI Story Understanding & Explanation Writing

### Multi-Tier AI Provider System
* **Architecture**: Pluggable AI engine supporting local offline heuristics, local LLMs (via Ollama / llama.cpp / lightweight transformers), and OpenAI-compatible API endpoints (Gemini, Groq, DeepSeek, Claude, GPT).
* **Chunking Engine**: 3-8 minute rolling windows with 30-45s overlap to reconstruct narrative causality, character introductions, plot twists, climax, and resolution without exceeding RAM limits.
* **Script Writer & Localizer**: Generates native YouTube-style recaps with human-paced storytelling, natural pauses, idiomatic Bengali, natural Hindi, and engaging English.
* **Fallback Strategy**: Built-in structured extractive & generative narrative heuristics that build complete story recaps even without external API keys or heavy GPU clusters.

---

## 5. Thumbnail & Visual Composition

### Pillow (PIL) + Noto Sans Multilingual Fonts
* **GitHub URL**: [https://github.com/python-pillow/Pillow](https://github.com/python-pillow/Pillow) & [https://github.com/notofonts/bengali](https://github.com/notofonts/bengali)
* **Purpose**: Story-driven thumbnail composition with high-contrast typography, cinematic vignette gradients, visual badges, and dramatic scene frame extraction.
* **License**: HPND / OFL (Open Font License)
* **Why Selected**: Low memory, pixel-perfect rendering of complex Bengali, Devanagari, and Latin scripts.

---

## 6. Architecture & Memory Management

* **Zero-Full-Load Guarantee**: Video and audio are never loaded entirely into memory. All chunking, clipping, and concatenation operate through temporary files and streaming pipelines.
* **Disk Space Gate**: Pre-flight checks verify minimum 5GB free disk space before processing.
* **State Resumption**: `project_state.json` tracks pipeline stages (media analysis, subtitle extraction, story analysis, script writing, TTS generation, timeline mapping, rendering, thumbnail, QA) so any interrupted process can resume instantly without recomputing completed phases.
