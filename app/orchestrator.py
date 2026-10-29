"""End-to-End Orchestrator executing the 10-phase Movie Explanation Studio pipeline."""

import os
import time
import shutil
from typing import Optional, Dict, Any
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

import sys
from app.core.config import Config, ExplanationParams
from app.core.project import Project
from app.core.state import PipelineStage, StageStatus
from app.core.logger import get_logger
from app.core.models import ScriptVersion, VoiceConfiguration, PreviewApproval, DeliveryProfile
from app.review.script_reviewer import ScriptReviewManager
from app.review.voice_audition import VoiceAuditionManager
from app.tts.google_adapters import get_voice_adapter, UnifiedVoiceAdapter
from app.audio.post_processor import AudioPostProcessor
from app.utils.disk import check_disk_space_sufficient
from app.utils.files import safe_write_json, safe_read_json, list_media_files
from app.utils.timecode import format_duration_human
from app.media.probe import probe_media_file
from app.media.subtitles import (
    find_sidecar_subtitles,
    extract_embedded_subtitles,
    parse_subtitle_file,
    normalize_subtitles,
    create_chunks_from_timeline
)
from app.media.audio import extract_mono_speech_audio, transcribe_audio_whisper
from app.media.scenes import detect_movie_scenes
from app.ai.provider import get_ai_provider
from app.ai.story_researcher import research_movie
from app.ai.chunk_analyzer import analyze_all_chunks
from app.ai.story_mapper import build_master_story_map
from app.ai.script_writer import generate_explanation_script

from app.tts.pipeline import get_tts_provider, synthesize_script_narration
from app.editing.timeline import build_explanation_timeline
from app.editing.subtitles import generate_explanation_subtitles
from app.editing.renderer import render_explanation_video
from app.editing.multi_track import run_multilang_export
from app.thumbnail.generator import create_thumbnail
from app.metadata.generator import generate_metadata
from app.qa.validator import perform_automated_qa, SAFETY_DISCLAIMER

console = Console()
logger = get_logger()


class StudioOrchestrator:
    """Coordinates execution across all 10 pipeline stages with low-RAM streaming and error recovery."""

    def __init__(self, movie_path: str, config: Config, params: Optional[ExplanationParams] = None):
        self.movie_path = os.path.abspath(os.path.expanduser(movie_path))
        self.config = config
        self.params = params or ExplanationParams()
        self.project = Project(self.movie_path, self.config, self.params)
        self.state = self.project.state
        self.ai_provider = get_ai_provider(self.config.data.get("ai"))
        self.tts_provider = get_tts_provider(self.config.get("tts.preferred_engine", "edge-tts"))
        self.voice_adapter = get_voice_adapter(self.config.get("tts.preferred_engine", "auto"))
        self.script_reviewer = ScriptReviewManager(self.project.dirs["scripts"])
        self.voice_audition_mgr = VoiceAuditionManager(os.path.join(self.project.dirs["narration"], "previews"))
        self.post_processor = AudioPostProcessor()

    def run_pipeline(self, resume_mode: bool = False, interactive_approval: bool = False, auto_approve: bool = True) -> Dict[str, Any]:
        """Execute all pipeline stages sequentially with script review and voice audition gates."""
        start_time = time.time()

        console.print(Panel(
            SAFETY_DISCLAIMER.strip(),
            title="[bold red]RIGHTS & SAFETY GATE[/bold red]",
            border_style="red"
        ))

        # Check disk space before proceeding
        disk_ok, disk_msg = check_disk_space_sufficient(
            self.config.projects_dir,
            min_free_gb=self.config.min_disk_free_gb
        )
        if not disk_ok:
            console.print(f"[bold red]ERROR:[/bold red] {disk_msg}")
            raise RuntimeError(disk_msg)

        logger.info(f"Starting Movie Explanation Studio for '{self.project.movie_filename}' (Lang: {self.params.language_name}, Target: {self.params.duration_minutes}m)")

        # -------------------------------------------------------------
        # STAGE 1: Media Inspection (FFprobe)
        # -------------------------------------------------------------
        stage = PipelineStage.MEDIA_INSPECTION
        if resume_mode and self.state.is_stage_completed(stage):
            console.print(f"[cyan][1/10] Inspecting movie[/cyan] [dim](Cached)[/dim]")
            probe_info = safe_read_json(self.project.get_path("analysis", "probe_info.json"))
        else:
            console.print(f"[bold green][1/10][/bold green] [bold]Inspecting movie metadata and streams...[/bold]")
            self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
            try:
                probe_info = probe_media_file(self.movie_path)
                safe_write_json(self.project.get_path("analysis", "probe_info.json"), probe_info)
                self.state.set_stage_status(stage, StageStatus.COMPLETED, meta={"duration": probe_info["duration_seconds"]})
            except Exception as e:
                self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
                raise

        total_movie_duration = float(probe_info.get("duration_seconds", 3600.0))

        # -------------------------------------------------------------
        # STAGE 2: Subtitle-First Extraction & Normalization
        # -------------------------------------------------------------
        stage = PipelineStage.SUBTITLE_EXTRACTION
        if resume_mode and self.state.is_stage_completed(stage):
            console.print(f"[cyan][2/10] Extracting subtitles & transcripts[/cyan] [dim](Cached)[/dim]")
            normalized_cues = safe_read_json(self.project.get_path("subtitles", "normalized_transcript.json"))
        else:
            console.print(f"[bold green][2/10][/bold green] [bold]Extracting subtitles (Subtitle-First Pipeline)...[/bold]")
            self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
            try:
                raw_cues = []
                # Check sidecar subtitle files
                sidecars = find_sidecar_subtitles(self.movie_path)
                if sidecars:
                    logger.info(f"Found {len(sidecars)} sidecar subtitle file(s): {sidecars[0]}")
                    raw_cues = parse_subtitle_file(sidecars[0])

                # If no sidecars, extract embedded tracks
                if not raw_cues:
                    embedded_subs = extract_embedded_subtitles(self.movie_path, self.project.dirs["subtitles"], probe_info)
                    if embedded_subs:
                        raw_cues = parse_subtitle_file(embedded_subs[0])

                # If no subtitles found anywhere, fallback to faster-whisper STT
                if not raw_cues:
                    console.print("[yellow]No subtitles found. Running faster-whisper CPU Speech-to-Text...[/yellow]")
                    wav_path = self.project.get_path("audio", "dialogue_mono_16k.wav")
                    extract_mono_speech_audio(self.movie_path, wav_path)
                    raw_cues = transcribe_audio_whisper(
                        wav_path,
                        model_size=self.config.get("stt.model", "base"),
                        device=self.config.get("stt.device", "cpu"),
                        compute_type=self.config.get("stt.compute_type", "int8")
                    )

                normalized_cues = normalize_subtitles(raw_cues)
                safe_write_json(self.project.get_path("subtitles", "normalized_transcript.json"), normalized_cues)
                self.state.set_stage_status(stage, StageStatus.COMPLETED, meta={"cues_count": len(normalized_cues)})
            except Exception as e:
                self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
                raise

        # -------------------------------------------------------------
        # STAGE 3: Timeline Chunking & Scene Detection
        # -------------------------------------------------------------
        stage = PipelineStage.SCENE_DETECTION
        if resume_mode and self.state.is_stage_completed(stage):
            console.print(f"[cyan][3/10] Building timeline & scene detection[/cyan] [dim](Cached)[/dim]")
            scenes = safe_read_json(self.project.get_path("scenes", "scenes.json"))
            chunks = safe_read_json(self.project.get_path("analysis", "timeline_chunks.json"))
        else:
            console.print(f"[bold green][3/10][/bold green] [bold]Detecting scene boundaries and building narrative chunks...[/bold]")
            self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
            try:
                # 1. Scene detection
                scenes = detect_movie_scenes(self.movie_path, total_movie_duration)
                safe_write_json(self.project.get_path("scenes", "scenes.json"), scenes)

                # 2. Narrative Chunking (3-8 min windows with overlap)
                chunk_duration = float(self.config.get("story.chunk_duration_seconds", 300))
                overlap_sec = float(self.config.get("story.chunk_overlap_seconds", 35))
                chunks = create_chunks_from_timeline(normalized_cues, total_movie_duration, chunk_duration, overlap_sec)
                safe_write_json(self.project.get_path("analysis", "timeline_chunks.json"), chunks)

                self.state.set_stage_status(stage, StageStatus.COMPLETED, meta={"scenes_count": len(scenes), "chunks_count": len(chunks)})
            except Exception as e:
                self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
                raise

        # -------------------------------------------------------------
        # Online Story Research & Character Identification
        # -------------------------------------------------------------
        research_cache_path = self.project.get_path("analysis", "story_research.json")
        if resume_mode and os.path.isfile(research_cache_path):
            story_research = safe_read_json(research_cache_path)
        else:
            console.print(f"[bold cyan]🔍 Researching online synopsis & characters for '{self.project.movie_filename}'...[/bold cyan]")
            story_research = research_movie(self.project.movie_filename)
            safe_write_json(research_cache_path, story_research)

        # -------------------------------------------------------------
        # STAGE 4: Chunk-Level Story Understanding
        # -------------------------------------------------------------
        stage = PipelineStage.STORY_ANALYSIS
        if resume_mode and self.state.is_stage_completed(stage):
            console.print(f"[cyan][4/10] Understanding story chunks[/cyan] [dim](Cached)[/dim]")
            chunk_analyses = safe_read_json(self.project.get_path("analysis", "chunk_analysis.json"))
        else:
            console.print(f"[bold green][4/10][/bold green] [bold]Understanding story & character arcs across {len(chunks)} chunks...[/bold]")
            self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
            try:
                chunk_analyses = analyze_all_chunks(chunks, self.project.dirs["analysis"], self.ai_provider)
                self.state.set_stage_status(stage, StageStatus.COMPLETED, meta={"analyzed_chunks": len(chunk_analyses)})
            except Exception as e:
                self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
                raise

        # -------------------------------------------------------------
        # STAGE 5: Global Master Story Map Reconstruction
        # -------------------------------------------------------------
        stage = PipelineStage.MASTER_STORY_MAP
        if resume_mode and self.state.is_stage_completed(stage):
            console.print(f"[cyan][5/10] Master story map[/cyan] [dim](Cached)[/dim]")
            master_story = safe_read_json(self.project.get_path("analysis", "master_story.json"))
        else:
            console.print(f"[bold green][5/10][/bold green] [bold]Reconstructing global Master Story Map...[/bold]")
            self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
            try:
                master_story = build_master_story_map(
                    chunk_analyses,
                    self.project.get_path("analysis", "master_story.json"),
                    self.ai_provider,
                    story_research=story_research
                )
                self.state.set_stage_status(stage, StageStatus.COMPLETED)
            except Exception as e:
                self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
                raise

        # -------------------------------------------------------------
        # STAGE 6: Explanation Script Generation
        # -------------------------------------------------------------
        stage = PipelineStage.SCRIPT_GENERATION
        script_manifest_path = self.project.get_path("scripts", f"script_{self.params.language}_manifest.json")
        if resume_mode and self.state.is_stage_completed(stage) and os.path.isfile(script_manifest_path):
            console.print(f"[cyan][6/10] Explanation script[/cyan] [dim](Cached)[/dim]")
            script_manifest = safe_read_json(script_manifest_path)
        else:
            console.print(f"[bold green][6/10][/bold green] [bold]Writing original {self.params.language_name} explanation script...[/bold]")
            self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
            try:
                script_manifest = generate_explanation_script(
                    master_story=master_story,
                    chunk_analyses=chunk_analyses,
                    target_duration_minutes=self.params.duration_minutes,
                    language=self.params.language,
                    narration_style=self.params.narration_style,
                    output_dir=self.project.dirs["scripts"],
                    ai_provider=self.ai_provider,
                    story_research=story_research
                )
                self.state.set_stage_status(stage, StageStatus.COMPLETED, meta={"words": script_manifest["total_words"]})
            except Exception as e:
                self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
                raise

        # -------------------------------------------------------------
        # STAGE 6.5: Script Review & User Approval Gate
        # -------------------------------------------------------------
        stage = PipelineStage.SCRIPT_REVIEW
        script_version = self.script_reviewer.load_script_version(script_manifest_path)

        if not self.script_reviewer.is_approved(script_version):
            if interactive_approval and sys.stdin.isatty():
                script_version = self._run_interactive_script_review(script_version, script_manifest_path)
            elif auto_approve:
                console.print(f"[bold green]✓ Auto-approving script version '{script_version.script_version_id}' (Hash: {script_version.content_hash})[/bold green]")
                self.script_reviewer.approve_script(script_version)
                self.script_reviewer.save_script_version(script_version, script_manifest_path)
            else:
                err = f"Script version '{script_version.script_version_id}' is unapproved. Review and approval required."
                self.state.set_stage_status(stage, StageStatus.FAILED, error=err)
                raise RuntimeError(err)

        self.state.set_stage_status(
            stage,
            StageStatus.COMPLETED,
            meta={"script_version_id": script_version.script_version_id, "content_hash": script_version.content_hash}
        )

        # -------------------------------------------------------------
        # STAGE 6.6: Voice Selection, Audition & Preview Approval Gate
        # -------------------------------------------------------------
        stage = PipelineStage.VOICE_AUDITION
        voice_approval_path = self.project.get_path("narration", "preview_approval.json")
        available_voices = self.voice_adapter.list_voices(self.params.language)
        chosen_voice_id = available_voices[0]["id"] if available_voices else "default"

        voice_cfg = VoiceConfiguration(
            provider=self.voice_adapter.name,
            model=getattr(self.voice_adapter, "model", "default"),
            voice_id=chosen_voice_id,
            language=self.params.language,
            speaking_rate=float(self.config.get("narration.speed", 1.0)),
            pitch=float(self.config.get("narration.pitch", -8.0))
        )

        if not self.voice_audition_mgr.is_preview_valid(voice_approval_path, script_version.script_version_id, voice_cfg):
            if interactive_approval and sys.stdin.isatty():
                preview_approval = self._run_interactive_voice_audition(script_version, voice_cfg, voice_approval_path)
            elif auto_approve:
                console.print(f"[bold green]✓ Generating 3-passage voice audition for '{voice_cfg.voice_id}' (Pitch: {voice_cfg.pitch:+0.0f}Hz)...[/bold green]")
                previews = self.voice_audition_mgr.generate_voice_audition(
                    adapter=self.voice_adapter,
                    voice_id=voice_cfg.voice_id,
                    language=self.params.language,
                    pronunciation_dict=script_version.pronunciation_dictionary,
                    pitch=voice_cfg.pitch
                )
                preview_approval = self.voice_audition_mgr.approve_voice_preview(
                    script_version_id=script_version.script_version_id,
                    voice_config=voice_cfg,
                    preview_files=previews,
                    approval_file_path=voice_approval_path
                )
            else:
                err = f"Voice preview for script '{script_version.script_version_id}' is unapproved. Audition required."
                self.state.set_stage_status(stage, StageStatus.FAILED, error=err)
                raise RuntimeError(err)

        self.state.set_stage_status(
            stage,
            StageStatus.COMPLETED,
            meta={"voice_id": voice_cfg.voice_id, "provider": voice_cfg.provider}
        )

        # -------------------------------------------------------------
        # STAGE 7: Chunked Narration Voice Synthesis & Audio Mastering
        # -------------------------------------------------------------
        stage = PipelineStage.VOICE_SYNTHESIS
        voice_manifest = None
        if resume_mode and self.state.is_stage_completed(stage):
            cached_manifest = safe_read_json(self.project.get_path("narration", "voice_manifest.json"))
            master_file = cached_manifest.get("full_narration_file") if cached_manifest else None
            target_min_sec = (self.params.duration_minutes * 60) * 0.70
            if (
                cached_manifest
                and master_file
                and os.path.isfile(master_file)
                and cached_manifest.get("total_duration_seconds", 0) >= target_min_sec
            ):
                console.print(f"[cyan][7/10] Voice synthesis & mastering[/cyan] [dim](Cached)[/dim]")
                voice_manifest = cached_manifest
            else:
                logger.info("Cached voice manifest is missing, truncated, or incomplete. Synthesizing fresh narration...")

        if not voice_manifest:
            console.print(f"[bold green][7/10][/bold green] [bold]Generating natural {self.params.language_name} voice-over ({self.voice_adapter.name})...[/bold]")
            self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
            try:
                voice_manifest = synthesize_script_narration(
                    script_manifest=script_version.to_dict(),
                    output_dir=self.project.dirs["narration"],
                    tts_provider=self.voice_adapter,
                    speed=float(self.config.get("narration.speed", 1.0)),
                    voice_id=voice_cfg.voice_id,
                    pitch=voice_cfg.pitch,
                    sync_to_video=False
                )

                self.state.set_stage_status(stage, StageStatus.COMPLETED, meta={"duration": voice_manifest["total_duration_seconds"]})
                self.state.set_stage_status(PipelineStage.AUDIO_FINISHING, StageStatus.COMPLETED)
            except Exception as e:
                self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
                raise

        # -------------------------------------------------------------
        # STAGE 8: Timeline Mapping & Subtitles Generation
        # -------------------------------------------------------------
        stage = PipelineStage.TIMELINE_MAPPING
        timeline_data = None
        if resume_mode and self.state.is_stage_completed(stage):
            cached_tl = safe_read_json(self.project.get_path("render", "timeline.json"))
            if (
                cached_tl
                and abs(cached_tl.get("total_duration_seconds", 0) - voice_manifest.get("total_duration_seconds", 0)) < 2.0
            ):
                console.print(f"[cyan][8/10] Timeline mapping & subtitles[/cyan] [dim](Cached)[/dim]")
                timeline_data = cached_tl
            else:
                logger.info("Cached timeline duration does not match narration. Re-mapping timeline...")

        if not timeline_data:
            console.print(f"[bold green][8/10][/bold green] [bold]Mapping supporting visual cuts and generating subtitles...[/bold]")
            self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
            try:
                timeline_data = build_explanation_timeline(
                    voice_manifest=voice_manifest,
                    scenes=scenes,
                    total_movie_duration=total_movie_duration,
                    output_path=self.project.get_path("render", "timeline.json"),
                    chunk_analyses=chunk_analyses
                )
                generate_explanation_subtitles(
                    timeline_data=timeline_data,
                    output_srt_path=self.project.get_path("subtitles", "final.srt"),
                    output_ass_path=self.project.get_path("subtitles", "final.ass")
                )
                self.state.set_stage_status(stage, StageStatus.COMPLETED)
            except Exception as e:
                self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
                raise

        # -------------------------------------------------------------
        # STAGE 9: Low-RAM Video Rendering
        # -------------------------------------------------------------
        stage = PipelineStage.VIDEO_RENDERING
        final_video_path = None
        if resume_mode and self.state.is_stage_completed(stage):
            cand_video = self.project.get_path("render", "final.mp4")
            if os.path.isfile(cand_video):
                probe = probe_media_file(cand_video)
                v_dur = float(probe.get("duration_seconds", 0))
                if abs(v_dur - timeline_data.get("total_duration_seconds", 0)) < 5.0 and v_dur >= (self.params.duration_minutes * 60 * 0.7):
                    console.print(f"[cyan][9/10] Video rendering[/cyan] [dim](Cached)[/dim]")
                    final_video_path = cand_video
                else:
                    logger.info(f"Cached video duration ({v_dur}s) does not match timeline ({timeline_data.get('total_duration_seconds')}s). Re-rendering...")

        if not final_video_path:
            console.print(f"[bold green][9/10][/bold green] [bold]Rendering final video with streaming FFmpeg composition...[/bold]")
            self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
            try:
                final_video_path = render_explanation_video(
                    source_movie_path=self.movie_path,
                    timeline_data=timeline_data,
                    master_narration_audio_path=voice_manifest["full_narration_file"],
                    output_video_path=self.project.get_path("render", "final.mp4"),
                    temp_dir=os.path.join(self.project.dirs["cache"], "render_temp"),
                    aspect_ratio=self.params.aspect_ratio,
                    resolution=self.params.resolution,
                    preset=self.config.get("video.preset", "faster"),
                    crf=int(self.config.get("video.crf", 22)),
                    visual_mode=self.config.get("video.visual_mode", "still_motion"),
                    max_workers=int(self.config.get("processing.max_workers", 3))
                )
                self.state.set_stage_status(stage, StageStatus.COMPLETED)
            except Exception as e:
                self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
                raise

        # -------------------------------------------------------------
        # STAGE 10: Thumbnail, Metadata & Final Automated QA
        # -------------------------------------------------------------
        stage = PipelineStage.THUMBNAIL_GENERATION
        console.print(f"[bold green][10/10][/bold green] [bold]Generating thumbnail, YouTube metadata, and performing QA...[/bold]")
        self.state.set_stage_status(stage, StageStatus.IN_PROGRESS)
        try:
            # 1. Thumbnail
            thumb_path = create_thumbnail(
                movie_path=self.movie_path,
                master_story=master_story,
                scenes=scenes,
                output_dir=self.project.dirs["thumbnail"],
                language=self.params.language
            )

            # 2. Metadata
            generate_metadata(
                movie_filename=self.project.movie_filename,
                master_story=master_story,
                timeline_data=timeline_data,
                language=self.params.language,
                duration_target_minutes=self.params.duration_minutes,
                narration_style=self.params.narration_style,
                output_dir=self.project.dirs["metadata"]
            )
            self.state.set_stage_status(PipelineStage.METADATA_GENERATION, StageStatus.COMPLETED)

            # 3. Final QA Audit
            qa_report = perform_automated_qa(
                rendered_video_path=self.project.get_path("render", "final.mp4"),
                subtitles_srt_path=self.project.get_path("subtitles", "final.srt"),
                master_narration_audio_path=voice_manifest["full_narration_file"],
                target_duration_minutes=self.params.duration_minutes,
                output_report_path=self.project.get_path("analysis", "qa_report.json")
            )

            self.state.set_stage_status(PipelineStage.THUMBNAIL_GENERATION, StageStatus.COMPLETED)
            self.state.set_stage_status(PipelineStage.FINAL_QA, StageStatus.COMPLETED)
        except Exception as e:
            self.state.set_stage_status(stage, StageStatus.FAILED, error=str(e))
            raise

        # Deliver final deliverables to global and project output dirs
        deliverables = self.project.deliver_final_outputs(self.params.language_name)

        # -------------------------------------------------------------
        # STAGE 11 (OPTIONAL): Multi-Language YouTube Export
        # Runs only when extra_languages are specified.
        # -------------------------------------------------------------
        multilang_result = None
        extra_langs = getattr(self.params, "extra_languages", []) or []
        if extra_langs:
            console.print(
                f"\n[bold green][11/10+][/bold green] [bold]Generating multi-language YouTube export "
                f"({', '.join(l.upper() for l in extra_langs)})...[/bold]"
            )
            try:
                multilang_result = self._run_multilang_stage(
                    master_story=master_story,
                    chunk_analyses=chunk_analyses,
                    primary_voice_manifest=voice_manifest,
                    primary_srt=self.project.get_path("subtitles", "final.srt"),
                    primary_video=self.project.get_path("render", "final.mp4"),
                    extra_langs=extra_langs
                )
                if multilang_result:
                    deliverables["multilang_video"] = multilang_result.get("multilang_video", "")
                    deliverables["youtube_guide"] = multilang_result.get("youtube_guide", "")

                    # Also copy multilang video into the user's delivery folder
                    delivery_dir = deliverables.get("delivery_folder", "")
                    if delivery_dir and os.path.isdir(delivery_dir):
                        ml_src = multilang_result.get("multilang_video", "")
                        yt_src = multilang_result.get("youtube_guide", "")
                        if ml_src and os.path.isfile(ml_src):
                            ml_dst = os.path.join(delivery_dir, "final_multilang.mp4")
                            shutil.copy2(ml_src, ml_dst)
                            deliverables["multilang_video"] = ml_dst
                        if yt_src and os.path.isfile(yt_src):
                            yt_dst = os.path.join(delivery_dir, "youtube_upload_guide.txt")
                            shutil.copy2(yt_src, yt_dst)
                            deliverables["youtube_guide"] = yt_dst

                    console.print(
                        f"  [green]✓[/green] Multi-language video: "
                        f"[cyan]{deliverables.get('multilang_video', '')}[/cyan]"
                    )
                    console.print(
                        f"  [green]✓[/green] YouTube upload guide: "
                        f"[cyan]{deliverables.get('youtube_guide', '')}[/cyan]"
                    )
            except Exception as e:
                logger.warning(f"Multi-language export failed (non-fatal): {e}")


        elapsed_sec = round(time.time() - start_time, 1)

        # Print final formatted terminal report matching Section 34
        self._print_completion_report(qa_report, deliverables, elapsed_sec)

        return {
            "qa_report": qa_report,
            "deliverables": deliverables,
            "multilang": multilang_result,
            "elapsed_seconds": elapsed_sec
        }

    def _run_multilang_stage(
        self,
        master_story: Dict[str, Any],
        chunk_analyses: list,
        primary_voice_manifest: Dict[str, Any],
        primary_srt: str,
        primary_video: str,
        extra_langs: list
    ) -> Optional[Dict[str, Any]]:
        """Generate script+TTS for each extra language, then mux all into one video."""
        language_narration_map = {
            self.params.language: primary_voice_manifest["full_narration_file"]
        }
        language_srt_map = {self.params.language: primary_srt}

        for lang in extra_langs:
            logger.info(f"Generating [{lang.upper()}] script + narration for multi-language export...")
            lang_script_dir = os.path.join(self.project.dirs["analysis"], f"script_{lang}")
            lang_narr_dir = os.path.join(self.project.dirs["narration"], f"extra_{lang}")
            os.makedirs(lang_script_dir, exist_ok=True)
            os.makedirs(lang_narr_dir, exist_ok=True)

            try:
                # Generate script in this language
                lang_manifest = generate_explanation_script(
                    master_story=master_story,
                    chunk_analyses=chunk_analyses,
                    target_duration_minutes=self.params.duration_minutes,
                    language=lang,
                    narration_style=self.params.narration_style,
                    output_dir=lang_script_dir,
                    ai_provider=self.ai_provider
                )

                # Synthesize narration
                lang_voice = synthesize_script_narration(
                    script_manifest=lang_manifest,
                    output_dir=lang_narr_dir,
                    tts_provider=self.tts_provider,
                    speed=float(self.config.get("narration.speed", 1.0)),
                    sync_to_video=True
                )
                language_narration_map[lang] = lang_voice["full_narration_file"]

                # Generate subtitles for this language
                lang_srt = os.path.join(lang_narr_dir, f"final_{lang}.srt")
                # Build a minimal timeline for subtitle generation
                from app.editing.timeline import build_explanation_timeline
                from app.editing.subtitles import generate_explanation_subtitles
                # Reuse existing scenes from primary; build quick timeline
                lang_timeline_path = os.path.join(lang_narr_dir, "timeline.json")
                from app.utils.files import safe_read_json
                primary_timeline = safe_read_json(
                    self.project.get_path("analysis", "timeline.json"),
                    default={"items": []}
                )
                # Patch narration text from new language segments
                patched_items = []
                segs = lang_manifest.get("segments", [])
                for i, item in enumerate(primary_timeline.get("items", [])):
                    patched = dict(item)
                    if i < len(segs):
                        patched["narration_text"] = segs[i].get("narration_text", item.get("narration_text", ""))
                    patched_items.append(patched)
                lang_timeline = dict(primary_timeline)
                lang_timeline["items"] = patched_items
                generate_explanation_subtitles(
                    timeline_data=lang_timeline,
                    output_srt_path=lang_srt
                )
                language_srt_map[lang] = lang_srt
                logger.info(f"[{lang.upper()}] narration + subtitles ready.")

            except Exception as e:
                logger.warning(f"[{lang.upper()}] generation failed, skipping: {e}")
                continue

        # Need at least 2 languages to do multi-track
        if len(language_narration_map) < 2:
            logger.warning("Only 1 language available — skipping multi-track mux.")
            return None

        multilang_dir = os.path.join(self.project.dirs["output"], "youtube_multilang")
        return run_multilang_export(
            primary_video_path=primary_video,
            primary_language=self.params.language,
            language_narration_map=language_narration_map,
            language_srt_map=language_srt_map,
            output_dir=multilang_dir,
            movie_title=os.path.splitext(self.project.movie_filename)[0],
            preset=self.config.get("video.preset", "faster"),
            crf=int(self.config.get("video.crf", 22))
        )

    def _print_completion_report(self, qa_report: Dict[str, Any], deliverables: Dict[str, str], elapsed_sec: float) -> None:
        """Print stylized final terminal report."""
        report_text = f"""
[bold cyan]==================================================[/bold cyan]
[bold white]MOVIE EXPLANATION COMPLETE[/bold white]
[bold cyan]==========================[/bold cyan]

[bold yellow]Movie:[/bold yellow]
{self.project.movie_filename}

[bold yellow]Language:[/bold yellow]
{self.params.language_name}

[bold yellow]Target:[/bold yellow]
{self.params.duration_minutes} minutes

[bold yellow]Actual:[/bold yellow]
{qa_report.get('actual_duration_human', 'N/A')}

[bold yellow]Video:[/bold yellow]
{deliverables.get('video')}

[bold yellow]Thumbnail:[/bold yellow]
{deliverables.get('thumbnail')}

[bold yellow]Script:[/bold yellow]
{deliverables.get('script')}

[bold yellow]Subtitles:[/bold yellow]
{deliverables.get('subtitles_srt')}

[bold yellow]Metadata:[/bold yellow]
{deliverables.get('metadata')}

[bold yellow]QA Status:[/bold yellow]
{qa_report.get('status')} (Manual Review Required: {qa_report.get('manual_review_required')})

[bold yellow]Elapsed Time:[/bold yellow]
{format_duration_human(elapsed_sec)}

[bold cyan]==================================================[/bold cyan]
[bold green]PROCESSING COMPLETE[/bold green]
[bold cyan]===================[/bold cyan]
"""
        console.print(Panel(report_text.strip(), title="[bold green]SUCCESS[/bold green]", border_style="green"))

    def _run_interactive_script_review(self, script_version: ScriptVersion, manifest_path: str) -> ScriptVersion:
        """Interactive terminal screen for reviewing, editing, and approving script version."""
        from rich.table import Table as RTable
        from rich.prompt import Prompt, IntPrompt

        while True:
            console.print(Panel(
                f"[bold cyan]SCRIPT REVIEW & APPROVAL GATE[/bold cyan]\n"
                f"Language: [bold white]{script_version.language.upper()}[/bold white] | "
                f"Segments: [bold white]{len(script_version.segments)}[/bold white] | "
                f"Total Words: [bold white]{script_version.total_words}[/bold white] | "
                f"Status: [bold yellow]{script_version.approval_status.upper()}[/bold yellow]\n"
                f"Pronunciation Rules: [dim]{len(script_version.pronunciation_dictionary)} words registered[/dim]",
                title="[bold green]STUDIO SCRIPT REVIEW[/bold green]",
                border_style="green"
            ))

            tbl = RTable(title="Narration Script Segments", border_style="cyan")
            tbl.add_column("#", style="dim", width=4)
            tbl.add_column("Act", style="cyan", width=14)
            tbl.add_column("Movie Time", style="yellow", width=22)
            tbl.add_column("Emotion", style="magenta", width=18)
            tbl.add_column("Spoken Text Preview", style="white")

            for s in script_version.segments[:10]:
                preview_txt = (s.narration_text[:65] + "...") if len(s.narration_text) > 65 else s.narration_text
                tbl.add_row(str(s.segment_id), s.act.title(), s.source_time_reference, s.emotion, preview_txt)

            if len(script_version.segments) > 10:
                tbl.add_row("...", f"+{len(script_version.segments)-10} more", "...", "...", "...")

            console.print(tbl)

            console.print("\n[bold]Review Options:[/bold]")
            console.print("  [cyan]1.[/cyan] Approve Script & Proceed to Voice Audition")
            console.print("  [cyan]2.[/cyan] View complete text of a segment")
            console.print("  [cyan]3.[/cyan] Edit a segment's narration text")
            console.print("  [cyan]4.[/cyan] Change segment emotion profile")
            console.print("  [cyan]5.[/cyan] Add/edit pronunciation dictionary rule")
            console.print("  [cyan]6.[/cyan] Regenerate a segment with AI")

            choice = Prompt.ask("Action", choices=["1", "2", "3", "4", "5", "6"], default="1")

            if choice == "1":
                self.script_reviewer.approve_script(script_version)
                self.script_reviewer.save_script_version(script_version, manifest_path)
                console.print(f"[bold green]✓ Script successfully approved (Version: {script_version.script_version_id})![/bold green]")
                return script_version

            elif choice == "2":
                sid = IntPrompt.ask("Enter segment number", default=1)
                seg = next((s for s in script_version.segments if s.segment_id == sid), None)
                if seg:
                    console.print(Panel(
                        f"[bold yellow]Act:[/bold yellow] {seg.act} | [bold yellow]Time:[/bold yellow] {seg.source_time_reference}\n"
                        f"[bold yellow]Emotion:[/bold yellow] {seg.emotion} (Pace: {seg.pacing:.2f}x)\n"
                        f"[bold yellow]Delivery Direction:[/bold yellow] {seg.delivery_notes}\n\n"
                        f"[bold white]{seg.narration_text}[/bold white]",
                        title=f"Segment #{sid}"
                    ))
                else:
                    console.print(f"[red]Segment #{sid} not found.[/red]")

            elif choice == "3":
                sid = IntPrompt.ask("Enter segment number to edit", default=1)
                seg = next((s for s in script_version.segments if s.segment_id == sid), None)
                if seg:
                    console.print(f"[dim]Current:[/dim] {seg.narration_text}")
                    new_text = Prompt.ask("Enter updated narration text")
                    if new_text.strip():
                        self.script_reviewer.edit_segment(script_version, sid, new_text)
                        self.script_reviewer.save_script_version(script_version, manifest_path)
                        console.print(f"[green]Segment #{sid} updated.[/green]")

            elif choice == "4":
                sid = IntPrompt.ask("Enter segment number", default=1)
                console.print(f"Available profiles: {', '.join(DeliveryProfile.ALL_PROFILES)}")
                new_emo = Prompt.ask("New emotion", choices=DeliveryProfile.ALL_PROFILES, default="suspense")
                self.script_reviewer.edit_segment(script_version, sid, seg.narration_text, new_emotion=new_emo)
                self.script_reviewer.save_script_version(script_version, manifest_path)
                console.print(f"[green]Segment #{sid} emotion updated to {new_emo}.[/green]")

            elif choice == "5":
                word = Prompt.ask("Enter word/character name")
                phonetic = Prompt.ask(f"Enter phonetic spelling for '{word}'")
                self.script_reviewer.add_pronunciation_entry(script_version, word, phonetic)
                self.script_reviewer.save_script_version(script_version, manifest_path)
                console.print(f"[green]Pronunciation rule added: {word} -> {phonetic}[/green]")

            elif choice == "6":
                sid = IntPrompt.ask("Enter segment number to regenerate", default=1)
                inst = Prompt.ask("Enter guidance (e.g. 'Make it more mysterious and dramatic')")
                console.print("[cyan]Regenerating segment with AI...[/cyan]")
                res = self.script_reviewer.regenerate_segment_text(script_version, sid, self.ai_provider, instructions=inst)
                if res:
                    self.script_reviewer.save_script_version(script_version, manifest_path)
                    console.print(f"[green]Regenerated Segment #{sid}:[/green] {res}")

    def _run_interactive_voice_audition(
        self,
        script_version: ScriptVersion,
        voice_cfg: VoiceConfiguration,
        voice_approval_path: str
    ) -> PreviewApproval:
        """Interactive voice audition screen generating normal, suspenseful, and emotional samples."""
        from rich.table import Table as RTable
        from rich.prompt import Prompt

        available_voices = self.voice_adapter.list_voices(self.params.language)

        console.print(Panel(
            f"[bold cyan]NARRATOR AUDITION & PREVIEW[/bold cyan]\n"
            f"Provider: [bold white]{self.voice_adapter.name.upper()}[/bold white] | "
            f"Language: [bold white]{self.params.language.upper()}[/bold white]\n"
            f"[dim]Audition the narrator across normal, suspenseful, and emotional passages before generation.[/dim]",
            title="[bold green]VOICE AUDITION STUDIO[/bold green]",
            border_style="green"
        ))

        tbl = RTable(title="Available Voices", border_style="cyan")
        tbl.add_column("#", style="dim", width=4)
        tbl.add_column("Voice ID", style="cyan")
        tbl.add_column("Name", style="white")
        tbl.add_column("Gender", style="yellow")
        tbl.add_column("Tier / Style", style="magenta")

        for idx, v in enumerate(available_voices):
            tbl.add_row(str(idx + 1), v.get("id"), v.get("name", v.get("id")), v.get("gender", "N/A"), v.get("tier", v.get("tone", "Neural")))

        console.print(tbl)

        choice_idx = Prompt.ask("Select narrator voice number", default="1")
        try:
            chosen = available_voices[int(choice_idx) - 1]
            voice_cfg.voice_id = chosen["id"]
        except Exception:
            voice_cfg.voice_id = available_voices[0]["id"] if available_voices else "default"

        console.print(f"\n[cyan]Generating 3-passage audition for [bold]{voice_cfg.voice_id}[/bold]...[/cyan]")
        previews = self.voice_audition_mgr.generate_voice_audition(
            adapter=self.voice_adapter,
            voice_id=voice_cfg.voice_id,
            language=self.params.language,
            pronunciation_dict=script_version.pronunciation_dictionary,
            pitch=voice_cfg.pitch
        )

        console.print(Panel(
            f"[bold green]Audition Passages Ready:[/bold green]\n"
            f"  1. [yellow]Normal Storytelling:[/yellow] {previews.get('normal')}\n"
            f"  2. [magenta]Suspense Passage:[/magenta] {previews.get('suspense')}\n"
            f"  3. [cyan]Emotional Revelation:[/cyan] {previews.get('emotional')}\n\n"
            f"[bold white]Please listen to verify tone, pronunciation, and pacing.[/bold white]",
            title="[bold green]AUDITION SAMPLES READY[/bold green]"
        ))

        confirm = Prompt.ask("Approve this narrator voice and begin full movie synthesis?", choices=["y", "n", "yes", "no"], default="y")
        if confirm.lower() in ("n", "no"):
            console.print("[yellow]Voice generation cancelled by user.[/yellow]")
            sys.exit(0)

        preview_approval = self.voice_audition_mgr.approve_voice_preview(
            script_version_id=script_version.script_version_id,
            voice_config=voice_cfg,
            preview_files=previews,
            approval_file_path=voice_approval_path
        )
        return preview_approval
