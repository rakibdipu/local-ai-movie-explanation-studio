"""Project state tracking and execution pipeline resumption."""

import os
import time
from typing import Dict, Any, Optional
from app.utils.files import safe_write_json, safe_read_json


class StageStatus:
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStage:
    MEDIA_INSPECTION = "media_inspection"
    SUBTITLE_EXTRACTION = "subtitle_extraction"
    SCENE_DETECTION = "scene_detection"
    STORY_ANALYSIS = "story_analysis"
    MASTER_STORY_MAP = "master_story_map"
    SCRIPT_GENERATION = "script_generation"
    SCRIPT_REVIEW = "script_review"
    VOICE_AUDITION = "voice_audition"
    VOICE_SYNTHESIS = "voice_synthesis"
    AUDIO_FINISHING = "audio_finishing"
    TIMELINE_MAPPING = "timeline_mapping"
    VIDEO_RENDERING = "video_rendering"
    THUMBNAIL_GENERATION = "thumbnail_generation"
    METADATA_GENERATION = "metadata_generation"
    FINAL_QA = "final_qa"

    ALL_STAGES = [
        MEDIA_INSPECTION,
        SUBTITLE_EXTRACTION,
        SCENE_DETECTION,
        STORY_ANALYSIS,
        MASTER_STORY_MAP,
        SCRIPT_GENERATION,
        SCRIPT_REVIEW,
        VOICE_AUDITION,
        VOICE_SYNTHESIS,
        AUDIO_FINISHING,
        TIMELINE_MAPPING,
        VIDEO_RENDERING,
        THUMBNAIL_GENERATION,
        METADATA_GENERATION,
        FINAL_QA,
    ]


class ProjectState:
    """Manages project_state.json for fault-tolerant resumption and stage monitoring."""

    def __init__(self, state_file_path: str, movie_hash: str, movie_path: str, base_state_file: Optional[str] = None):
        self.state_file_path = os.path.abspath(state_file_path)
        self.movie_hash = movie_hash
        self.movie_path = movie_path
        self.base_state_file = os.path.abspath(base_state_file) if base_state_file else None
        self.data: Dict[str, Any] = self._load_or_init()

    def _load_or_init(self) -> Dict[str, Any]:
        if os.path.isfile(self.state_file_path):
            try:
                return safe_read_json(self.state_file_path)
            except Exception:
                pass

        shared_stages = {
            PipelineStage.MEDIA_INSPECTION,
            PipelineStage.SUBTITLE_EXTRACTION,
            PipelineStage.SCENE_DETECTION,
            PipelineStage.STORY_ANALYSIS,
            PipelineStage.MASTER_STORY_MAP,
        }

        stages = {stage: StageStatus.PENDING for stage in PipelineStage.ALL_STAGES}
        stage_meta = {}

        # If base state exists, inherit completed shared stages (analysis, scenes, subtitles)
        if self.base_state_file and os.path.isfile(self.base_state_file):
            try:
                base_data = safe_read_json(self.base_state_file)
                base_stages = base_data.get("stages", {})
                base_meta = base_data.get("stage_meta", {})
                for st in shared_stages:
                    if base_stages.get(st) == StageStatus.COMPLETED:
                        stages[st] = StageStatus.COMPLETED
                        if st in base_meta:
                            stage_meta[st] = base_meta[st]
            except Exception:
                pass

        initial_state = {
            "movie_hash": self.movie_hash,
            "movie_file": os.path.basename(self.movie_path),
            "created_at": time.time(),
            "updated_at": time.time(),
            "status": "initialized",
            "stages": stages,
            "stage_meta": stage_meta,
            "error": None,
        }
        self._save(initial_state)
        return initial_state

    def _save(self, data: Optional[Dict[str, Any]] = None) -> None:
        if data is None:
            data = self.data
        data["updated_at"] = time.time()
        safe_write_json(self.state_file_path, data)

    def is_stage_completed(self, stage: str) -> bool:
        """Check whether a specific pipeline stage has already completed."""
        return self.data.get("stages", {}).get(stage) == StageStatus.COMPLETED

    def set_stage_status(self, stage: str, status: str, meta: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        """Update stage status and persist to project_state.json."""
        if "stages" not in self.data:
            self.data["stages"] = {}
        self.data["stages"][stage] = status

        if "stage_meta" not in self.data:
            self.data["stage_meta"] = {}

        if meta:
            self.data["stage_meta"][stage] = meta

        if error:
            self.data["error"] = {
                "stage": stage,
                "message": error,
                "timestamp": time.time()
            }
        elif status == StageStatus.COMPLETED:
            curr_err = self.data.get("error")
            if isinstance(curr_err, dict) and curr_err.get("stage") == stage:
                self.data["error"] = None

        self._save()

    def get_stage_meta(self, stage: str) -> Dict[str, Any]:
        """Retrieve stored metadata for a completed stage."""
        return self.data.get("stage_meta", {}).get(stage, {})

    def get_progress_summary(self) -> Dict[str, Any]:
        """Return an overview of completed vs pending stages."""
        stages = self.data.get("stages", {})
        completed = sum(1 for st in stages.values() if st == StageStatus.COMPLETED)
        total = len(PipelineStage.ALL_STAGES)
        return {
            "completed_stages": completed,
            "total_stages": total,
            "percentage": round((completed / total) * 100, 1),
            "stages": stages,
            "last_error": self.data.get("error")
        }
