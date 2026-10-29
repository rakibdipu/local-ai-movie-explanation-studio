"""Project directory hierarchy management and workspace initialization."""

import os
import shutil
from typing import Dict, Optional
from app.core.config import Config, ExplanationParams
from app.core.state import ProjectState
from app.core.logger import setup_logger, get_logger
from app.utils.files import compute_file_hash, ensure_dir


class Project:
    """Represents an active Movie Explanation workspace for a specific movie hash."""

    def __init__(self, movie_path: str, config: Config, params: Optional[ExplanationParams] = None):
        self.movie_path = os.path.abspath(os.path.expanduser(movie_path))
        if not os.path.isfile(self.movie_path):
            raise FileNotFoundError(f"Movie file not found: {self.movie_path}")

        self.config = config
        self.params = params or ExplanationParams()
        self.movie_filename = os.path.basename(self.movie_path)
        self.movie_hash = compute_file_hash(self.movie_path)

        # Base directories
        self.base_project_dir = os.path.join(self.config.projects_dir, self.movie_hash)
        project_name = f"{self.movie_hash}_{self.params.language}" if self.params.language != "bn" else self.movie_hash
        self.project_dir = os.path.join(self.config.projects_dir, project_name)

        self.dirs: Dict[str, str] = {
            "root": self.project_dir,
            "source": os.path.join(self.project_dir, "source"),
            "audio": os.path.join(self.project_dir, "audio"),
            "subtitles": os.path.join(self.project_dir, "subtitles"),
            "scenes": os.path.join(self.project_dir, "scenes"),
            "analysis": os.path.join(self.project_dir, "analysis"),
            "scripts": os.path.join(self.project_dir, "scripts"),
            "narration": os.path.join(self.project_dir, "narration"),
            "clips": os.path.join(self.project_dir, "clips"),
            "render": os.path.join(self.project_dir, "render"),
            "thumbnail": os.path.join(self.project_dir, "thumbnail"),
            "metadata": os.path.join(self.project_dir, "metadata"),
            "cache": os.path.join(self.project_dir, "cache"),
            "logs": os.path.join(self.project_dir, "logs"),
            "output": os.path.join(self.project_dir, "output", self.params.language_name.lower()),
        }
        self._init_directories()

        # Logger
        self.log_file = os.path.join(self.dirs["logs"], "app.log")
        self.logger = setup_logger(self.log_file)

        # State Manager
        self.state_file = os.path.join(self.project_dir, "project_state.json")
        base_state_file = os.path.join(self.base_project_dir, "project_state.json") if self.base_project_dir != self.project_dir else None
        self.state = ProjectState(self.state_file, self.movie_hash, self.movie_path, base_state_file=base_state_file)

    def _init_directories(self) -> None:
        """Create standard project directory hierarchy and inherit shared analysis if available."""
        for d in self.dirs.values():
            ensure_dir(d)
        
        # Ensure global output dir exists as well
        ensure_dir(self.config.output_dir)

        # Inherit analysis, scenes, and transcripts from base project if this is an alternate language project
        if hasattr(self, "base_project_dir") and self.base_project_dir != self.project_dir and os.path.isdir(self.base_project_dir):
            for sub in ["scenes", "analysis", "subtitles"]:
                base_sub = os.path.join(self.base_project_dir, sub)
                target_sub = self.dirs.get(sub)
                if os.path.isdir(base_sub) and target_sub:
                    for f in os.listdir(base_sub):
                        src_f = os.path.join(base_sub, f)
                        dst_f = os.path.join(target_sub, f)
                        if os.path.isfile(src_f) and not os.path.exists(dst_f):
                            if not f.startswith("final.") and not f.startswith("script_") and f != "qa_report.json":
                                shutil.copy2(src_f, dst_f)

    def get_path(self, category: str, filename: str) -> str:
        """Get absolute path to a file in a project subdirectory."""
        if category in self.dirs:
            return os.path.join(self.dirs[category], filename)
        return os.path.join(self.project_dir, category, filename)

    def deliver_final_outputs(self, language: str) -> Dict[str, str]:
        """Copy final artifacts into the user's chosen output folder.

        Output structure:
          <output_dir>/<MovieName>_<Language>/
            ├── final.mp4          ← main explanation video
            ├── final.srt          ← subtitles
            ├── final.ass          ← styled subtitles
            ├── thumbnail.png
            ├── script.txt
            ├── metadata.json
            └── qa_report.json
        """
        lang_dir_name = language.lower()

        # Build a clean folder name from the movie filename
        movie_stem = os.path.splitext(self.movie_filename)[0]
        # Remove special chars that are bad in directory names
        import re
        clean_stem = re.sub(r'[\\/*?:"<>|]', "_", movie_stem).strip()
        named_folder = f"{clean_stem}_{lang_dir_name}"

        # Final delivery goes directly into the global output dir in a named subfolder
        delivery_dir = os.path.join(self.config.output_dir, named_folder)
        ensure_dir(delivery_dir)

        # Find script file
        script_candidates = [
            os.path.join(self.dirs["scripts"], f"script_{self.params.language}.txt"),
            os.path.join(self.dirs["scripts"], f"script_{lang_dir_name}.txt"),
            os.path.join(self.dirs["scripts"], "script.txt"),
        ]
        script_src = next((p for p in script_candidates if os.path.isfile(p)), script_candidates[0])

        deliverables = {
            "video":          os.path.join(self.dirs["render"],    "final.mp4"),
            "subtitles_srt":  os.path.join(self.dirs["subtitles"], "final.srt"),
            "subtitles_ass":  os.path.join(self.dirs["subtitles"], "final.ass"),
            "thumbnail":      os.path.join(self.dirs["thumbnail"], "final_thumbnail.png"),
            "script":         script_src,
            "metadata":       os.path.join(self.dirs["metadata"],  "metadata.json"),
            "qa_report":      os.path.join(self.dirs["analysis"],  "qa_report.json"),
        }

        dest_names = {
            "video":         "final.mp4",
            "subtitles_srt": "final.srt",
            "subtitles_ass": "final.ass",
            "thumbnail":     "thumbnail.png",
            "script":        "script.txt",
            "metadata":      "metadata.json",
            "qa_report":     "qa_report.json",
        }

        copied_map = {}
        for key, src_path in deliverables.items():
            if os.path.exists(src_path):
                dst = os.path.join(delivery_dir, dest_names[key])
                shutil.copy2(src_path, dst)
                copied_map[key] = dst

        # Write a README inside the delivery folder
        readme = os.path.join(delivery_dir, "README.txt")
        with open(readme, "w", encoding="utf-8") as f:
            f.write(
                f"Movie Explanation — {movie_stem}\n"
                f"Language: {language}\n"
                f"Generated by AI Movie Explanation Studio\n\n"
                f"Files:\n"
                f"  final.mp4      — Main explanation video\n"
                f"  final.srt      — Subtitles (SRT)\n"
                f"  final.ass      — Styled subtitles (ASS)\n"
                f"  thumbnail.png  — YouTube thumbnail\n"
                f"  script.txt     — Narration script\n"
                f"  metadata.json  — YouTube title/description/tags\n"
                f"  qa_report.json — Automated quality report\n"
            )

        copied_map["delivery_folder"] = delivery_dir
        return copied_map

