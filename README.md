# Local AI Movie Explanation Studio

An enterprise-grade, modular, CPU-first **Local AI Movie Explanation Studio** designed for Ubuntu Linux (8 GB RAM, 512 GB SSD).

The studio takes a legally obtained movie/video file, analyzes the story, reconstructs the narrative arc, generates an original human-like recap script, synthesizes high-quality narration in the requested language (**English, Bangla, Hindi**), selects and cuts supporting scenes dynamically, renders a synchronized final video with subtitles, creates a dramatic YouTube-ready thumbnail, and generates complete metadata.

---

## 🎬 Demo & Sample Output

Check out sample movie explanations created with this system:
- 📺 [Demo Explanation Video 1](https://www.youtube.com/watch?v=9StEJ1muH-0&t=21s)
- 📺 [Demo Explanation Video 2](https://www.youtube.com/watch?v=IdQb-j4zAXw)

---

## 🌟 Key Features

* **Low-Resource & CPU-First**: Designed specifically for 8 GB RAM laptops. Video and audio are **never** loaded entirely into memory. All operations use streaming FFmpeg pipelines, chunking, temporary files, and caching.
* **Subtitle-First Pipeline**: If embedded (SRT/ASS/VTT) or sidecar subtitles exist, they are extracted, cleaned, and normalized without running Whisper unnecessarily. If subtitles are missing, falls back to CPU-optimized `faster-whisper` (INT8).
* **Multi-Tier AI Story Understanding**: Reconstructs complete 3-act story maps (Setup, Inciting Incident, Conflict, Escalation, Twists, Climax, Resolution) using pluggable AI engines (100% offline Local NLP heuristics, local Ollama, or Cloud LLMs).
* **Natural Spoken Recaps**: Generates human-like conversational YouTube narration scripts matching target speaking duration (130–165 WPM).
* **Native Localization**: Supports natural **Bangla (বাংলা)**, **Hindi (हिंदी)**, and **English** with culturally appropriate idioms and cadence.
* **Pluggable TTS Architecture**: Neural voices via Edge-TTS (`bn-BD-PradeepNeural`, `hi-IN-MadhurNeural`, `en-US-ChristopherNeural`), Kokoro-ONNX, Piper, and offline system fallbacks.
* **Intelligent Video Composition**: Maps narration segments to dynamic visual cuts from matching scenes, aligns durations, mixes audio with ducking, and burns in subtitles.
* **Curiosity-Driven Thumbnails**: Generates 3 story-driven concepts, extracts pivotal frames, and renders high-contrast YouTube thumbnails with multilingual typography.
* **Automated QA & Rights Gate**: Runs pre-delivery quality assurance checks (`qa_report.json`) and displays editorial rights verification guidelines.
* **Fault-Tolerant Resumption**: Tracks progress in `project_state.json`. If interrupted, `./run.sh resume` continues from the last completed stage.

---

## 🚀 Quick Start

### 1. Place your movie file in `input/`
```bash
cp /path/to/my_movie.mkv ./input/
```

### 2. Run Interactive Mode
```bash
./run.sh
```
Or:
```bash
python3 main.py
```

The system will detect the movie and guide you through an interactive setup:
```
Movie detected: my_movie.mkv

What language should the explanation use?
  1. English
  2. Bangla
  3. Hindi

Target explanation duration:
  1. 10 minutes
  2. 15 minutes
  3. 20 minutes
  4. 25 minutes
  5. 30 minutes
  6. Custom

Narration style:
  1. Cinematic storyteller
  2. Fast-paced YouTube narrator
  3. Serious documentary
  4. Mystery / detective
  5. Casual storyteller

Generate? [Y/n]
```

---

## ⚡ One-Line Natural Prompt Mode

Run complete automated generation directly from a single natural prompt:

```bash
# Bangla explanation (20 minutes)
./run.sh --prompt "Create a 20 minute Bangla movie explanation in cinematic storytelling style"

# Hindi explanation (15 minutes)
./run.sh --prompt "Explain this movie in Hindi in approximately 15 minutes"

# English fast-paced recap (10 minutes)
./run.sh --prompt "10 min fast-paced youtube recap in English"

# Vertical Shorts / Reels (9:16)
./run.sh --prompt "Make a 9:16 vertical shorts recap in Hindi for 10 min"
```

---

## 🛠️ CLI Subcommands

The studio provides comprehensive CLI tools:

```bash
# Run movie explanation
./run.sh run --language bn --duration 20

# Resume interrupted task from last completed stage
./run.sh resume

# Inspect video codecs, streams, audio tracks, and subtitles
./run.sh inspect

# Check project progress and stage completion statuses
./run.sh status

# Clean temporary cache and rendering workspace files
./run.sh clean
```

---

## 📂 Project Structure & Deliverables

Every movie gets a deterministic workspace based on its hash:

```
projects/<movie_hash>/
├── source/
├── audio/               # Extracted 16kHz mono audio / STT transcripts
├── subtitles/           # Normalized transcripts & final subtitles (final.srt, final.ass)
├── scenes/              # Scene boundary detection (scenes.json)
├── analysis/            # Chunk analysis, Master story map & QA report
├── scripts/             # Manifest & human-like scripts (script_bn.txt, etc.)
├── narration/           # Chunked audio segments (narration_001.wav...) & master audio
├── clips/               # Supporting visual cut list
├── render/              # Master timeline & rendered video (final.mp4)
├── thumbnail/           # Final thumbnail (final_thumbnail.png) & concepts
├── metadata/            # YouTube titles, description & hashtags (metadata.json)
├── cache/               # Intermediate stream cache
├── logs/                # Detailed application logs (app.log)
└── output/              # Published deliverables by language
    ├── bangla/
    │   ├── final.mp4
    │   ├── final.srt
    │   ├── final.ass
    │   ├── thumbnail.png
    │   ├── script.txt
    │   ├── metadata.json
    │   └── qa_report.json
```

---

## ⚙️ Configuration (`config.yaml`)

Edit [`config.yaml`](file:///home/dipu/Videos/movie%20expline/config.yaml) to customize video rendering, speech rates, TTS voices, and hardware limits:

```yaml
video:
  default_resolution: "1280x720" # Options: 1280x720, 1920x1080
  aspect_ratio: "16:9"           # Options: 16:9, 9:16, 1:1
  preset: "faster"               # Low CPU memory: ultrafast, faster, medium
  crf: 22

narration:
  default_language: "en"         # en, bn, hi
  default_style: "cinematic_storytelling"
  speed: 1.0

tts:
  preferred_engine: "edge-tts"   # edge-tts, kokoro, piper, system
```

---

## ⚖️ Rights & Safety Gate

```
IMPORTANT:
This tool does not guarantee copyright clearance.
Review the final video and verify your rights before publication.
```

The system strictly adheres to ethical transformational principles:
1. Emphasizes original commentary and educational story breakdowns.
2. Uses selective supporting visual clips and avoids uninterrupted duplication.
3. Automatically sets `manual_review_required: true` on all generated QA reports.
4. Generates YouTube-compliant rights disclaimers in all metadata files.
