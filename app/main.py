"""Command-Line Interface and Interactive User Experience for Movie Explanation Studio."""

import os
import sys
from typing import Optional
import click
from rich.console import Console
from rich.prompt import Prompt, IntPrompt
from rich.panel import Panel
from rich.table import Table

from app.core.config import Config, ExplanationParams, parse_natural_prompt, LANGUAGE_NAMES, STYLE_NAMES
from app.core.logger import setup_logger
from app.core.models import ScriptVersion, VoiceConfiguration, PreviewApproval
from app.utils.files import list_media_files, ensure_dir
from app.orchestrator import StudioOrchestrator
from app.media.probe import probe_media_file
from app.media.youtube import is_youtube_url, fetch_video_info, download_youtube_video
from app.qa.validator import SAFETY_DISCLAIMER

console = Console()


def find_input_movie(input_dir: str) -> Optional[str]:
    """Detect movie file in input directory or prompt user."""
    ensure_dir(input_dir)
    movies = list_media_files(input_dir)
    if len(movies) == 1:
        return movies[0]
    elif len(movies) > 1:
        console.print("[bold yellow]Multiple movie files detected in input directory:[/bold yellow]")
        for idx, m in enumerate(movies):
            console.print(f"  {idx + 1}. {os.path.basename(m)}")
        choice = IntPrompt.ask("Select movie number", default=1)
        return movies[max(0, min(len(movies) - 1, choice - 1))]
    return None


def download_from_youtube(
    url: str,
    config: Config,
    max_height: Optional[int] = None,
    auto_confirm: bool = False
) -> str:
    """Fetch metadata, confirm with user (unless auto_confirm), then download YouTube video.

    Returns the local path to the downloaded video file.
    """
    if max_height is None:
        res = config.get("video.default_resolution", "1280x720")
        max_height = 720 if "720" in str(res) else 1080
    console.print(f"\n[cyan]🔍 Fetching video info...[/cyan]")
    try:
        info = fetch_video_info(url)
    except Exception as exc:
        console.print(f"[bold red]Could not fetch video info: {exc}[/bold red]")
        raise SystemExit(1)

    duration_min = round(info["duration_seconds"] / 60, 1)

    from rich.table import Table as RTable
    tbl = RTable(title="[bold cyan]YouTube Video Info[/bold cyan]", border_style="cyan")
    tbl.add_column("Field", style="dim")
    tbl.add_column("Value", style="white")
    tbl.add_row("Title", info["title"])
    tbl.add_row("Uploader", info["uploader"])
    tbl.add_row("Duration", f"{duration_min} minutes ({info['duration_seconds']:.0f}s)")
    tbl.add_row("Resolution", info["resolution"])
    if info["filesize_approx_mb"]:
        tbl.add_row("Approx. Size", f"{info['filesize_approx_mb']} MB")
    console.print(tbl)

    if not auto_confirm:
        confirm = Prompt.ask(
            "\n[bold yellow]Download and process this video?[/bold yellow]",
            choices=["y", "n", "yes", "no"],
            default="y",
        )
        if confirm.lower() in ("n", "no"):
            console.print("[yellow]Download cancelled.[/yellow]")
            raise SystemExit(0)

    download_dir = config.input_dir
    ensure_dir(download_dir)

    console.print(f"\n[green]⬇  Downloading (max {max_height}p) to:[/green] {download_dir}\n")
    try:
        local_path, _ = download_youtube_video(
            url,
            download_dir,
            max_height=max_height,
            show_progress=True
        )
    except Exception as exc:
        console.print(f"[bold red]Download failed: {exc}[/bold red]")
        raise SystemExit(1)

    console.print(f"\n[bold green]✅ Download complete:[/bold green] {os.path.basename(local_path)}\n")
    return local_path



def interactive_wizard(movie_path: str, config: Config) -> ExplanationParams:
    """Run interactive question prompt wizard matching Section 1 specifications."""
    movie_name = os.path.basename(movie_path)
    
    console.print(Panel(
        f"[bold cyan]Movie detected:[/bold cyan] [bold white]{movie_name}[/bold white]\n\n"
        "[dim]Let's configure your movie explanation parameters:[/dim]",
        title="[bold green]LOCAL AI MOVIE EXPLANATION STUDIO[/bold green]",
        border_style="green"
    ))

    # 1. Language Selection
    console.print("\n[bold]What language should the explanation use?[/bold]\n")
    console.print("  [cyan]1.[/cyan] English")
    console.print("  [cyan]2.[/cyan] Bangla")
    console.print("  [cyan]3.[/cyan] Hindi\n")
    lang_choice = Prompt.ask("Language", choices=["1", "2", "3", "en", "bn", "hi", "English", "Bangla", "Hindi"], default="1")
    
    lang_map = {
        "1": "en", "english": "en", "en": "en",
        "2": "bn", "bangla": "bn", "bengali": "bn", "bn": "bn",
        "3": "hi", "hindi": "hi", "hi": "hi"
    }
    language = lang_map.get(lang_choice.lower(), "en")

    # 2. Target Duration Selection
    console.print("\n[bold]Target explanation duration:[/bold]\n")
    console.print("  [cyan]1.[/cyan] 10 minutes")
    console.print("  [cyan]2.[/cyan] 15 minutes")
    console.print("  [cyan]3.[/cyan] 20 minutes")
    console.print("  [cyan]4.[/cyan] 25 minutes")
    console.print("  [cyan]5.[/cyan] 30 minutes")
    console.print("  [cyan]6.[/cyan] Custom\n")
    dur_choice = Prompt.ask("Duration", choices=["1", "2", "3", "4", "5", "6", "10", "15", "20", "25", "30"], default="3")
    
    dur_map = {"1": 10, "2": 15, "3": 20, "4": 25, "5": 30, "10": 10, "15": 15, "20": 20, "25": 25, "30": 30}
    if dur_choice in dur_map:
        duration_minutes = dur_map[dur_choice]
    else:
        duration_minutes = IntPrompt.ask("Enter custom duration in minutes", default=20)

    # 3. Narration Style Selection
    console.print("\n[bold]Narration style:[/bold]\n")
    console.print("  [cyan]1.[/cyan] Cinematic storyteller")
    console.print("  [cyan]2.[/cyan] Fast-paced YouTube narrator")
    console.print("  [cyan]3.[/cyan] Serious documentary")
    console.print("  [cyan]4.[/cyan] Mystery / detective")
    console.print("  [cyan]5.[/cyan] Casual storyteller\n")
    style_choice = Prompt.ask("Narration style", choices=["1", "2", "3", "4", "5"], default="1")
    
    style_map = {
        "1": "cinematic_storytelling",
        "2": "fast_paced_youtube",
        "3": "serious_documentary",
        "4": "mystery_detective",
        "5": "casual_storyteller"
    }
    narration_style = style_map.get(style_choice, "cinematic_storytelling")

    # 4. Confirmation
    console.print("\n[bold green]Ready to generate explanation video![/bold green]")
    confirm = Prompt.ask("Generate?", choices=["y", "n", "yes", "no"], default="y")
    if confirm.lower() in ("n", "no"):
        console.print("[yellow]Generation aborted by user.[/yellow]")
        sys.exit(0)

    return ExplanationParams(
        language=language,
        duration_minutes=duration_minutes,
        narration_style=narration_style
    )


@click.group(invoke_without_command=True)
@click.option("--prompt", "-p", default=None, help="One-line natural language prompt (e.g. 'Create a 20 minute Hindi movie explanation')")
@click.option("--input", "-i", "input_file", default=None, help="Path to movie file OR a YouTube URL")
@click.option("--language", "-l", default=None, help="Target language code (en, bn, hi)")
@click.option("--duration", "-d", default=None, type=int, help="Target explanation duration in minutes")
@click.option("--style", "-s", default=None, help="Narration style")
@click.option("--aspect-ratio", "-a", default=None, help="Aspect ratio (16:9, 9:16, 1:1)")
@click.option("--resolution", "-r", default=None, help="Output resolution (1280x720, 1920x1080)")
@click.option("--review", is_flag=True, default=False, help="Open interactive script review and voice audition screen before synthesis")
@click.option("--auto-approve", "-y", is_flag=True, default=False, help="Auto-approve script and voice preview")
@click.option("--resume", is_flag=True, help="Resume previously interrupted process")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
@click.pass_context
def cli(ctx, prompt, input_file, language, duration, style, aspect_ratio, resolution, review, auto_approve, resume, config_file):
    """Local AI Movie Explanation Studio - CLI Entry Point."""
    if ctx.invoked_subcommand is not None:
        return

    config = Config(config_file)
    setup_logger()

    # ── Determine input movie (file OR YouTube URL) ──────────────────────────
    movie_path = None

    if input_file:
        if is_youtube_url(input_file):
            movie_path = download_from_youtube(input_file, config, auto_confirm=auto_approve)
        elif os.path.isfile(input_file):
            movie_path = input_file
        else:
            console.print(f"[bold red]File not found and not a recognised URL: {input_file}[/bold red]")
            sys.exit(1)

    if not movie_path:
        movie_path = find_input_movie(config.input_dir)

    if not movie_path:
        console.print(f"[bold yellow]No video found in '{config.input_dir}'.[/bold yellow]")
        user_input = Prompt.ask(
            "Enter a [bold]YouTube URL[/bold] or a local file path"
        ).strip()
        if is_youtube_url(user_input):
            movie_path = download_from_youtube(user_input, config, auto_confirm=auto_approve)
        elif os.path.isfile(user_input):
            movie_path = user_input
        else:
            console.print(f"[bold red]Not a valid URL or file path: {user_input}[/bold red]")
            sys.exit(1)

    # ── Determine parameters ─────────────────────────────────────────────────
    if prompt:
        console.print(f"[cyan]Parsing prompt:[/cyan] [italic]\"{prompt}\"[/italic]")
        params = parse_natural_prompt(prompt, default_duration=config.get("story.default_duration_minutes", 20))
        if language:
            params.language = language
        if duration:
            params.duration_minutes = duration
        if style:
            params.narration_style = style
        if aspect_ratio:
            params.aspect_ratio = aspect_ratio
        if resolution:
            params.resolution = resolution
    elif language or duration or style or aspect_ratio:
        params = ExplanationParams(
            language=language or config.get("narration.default_language", "en"),
            duration_minutes=duration or config.get("story.default_duration_minutes", 20),
            narration_style=style or config.get("narration.default_style", "cinematic_storytelling"),
            aspect_ratio=aspect_ratio or config.get("video.aspect_ratio", "16:9"),
            resolution=resolution or config.get("video.default_resolution", "1280x720")
        )
    else:
        # Interactive UI wizard
        params = interactive_wizard(movie_path, config)

    # Run orchestrator
    orchestrator = StudioOrchestrator(movie_path, config, params)
    interactive_mode = review or (not auto_approve and not prompt and sys.stdin.isatty())
    orchestrator.run_pipeline(
        resume_mode=resume,
        interactive_approval=interactive_mode,
        auto_approve=auto_approve or (not interactive_mode)
    )



@cli.command("youtube")
@click.argument("url")
@click.option("--prompt", "-p", default=None, help="One-line natural prompt")
@click.option("--language", "-l", default=None, help="Language (en, bn, hi)")
@click.option("--duration", "-d", default=None, type=int, help="Duration in minutes")
@click.option("--style", "-s", default=None, help="Narration style")
@click.option("--quality", "-q", default=1080, type=int, help="Max video height to download (720 or 1080)")
@click.option("--yes", "-y", is_flag=True, help="Skip download confirmation prompt")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
def youtube_cmd(url, prompt, language, duration, style, quality, yes, config_file):
    """Download a YouTube video and run the full explanation pipeline on it.

    \b
    Examples:
      python main.py youtube "https://youtu.be/dQw4w9WgXcQ"
      python main.py youtube "https://youtu.be/dQw4w9WgXcQ" -l bn -d 15 -s cinematic
    """
    config = Config(config_file)
    setup_logger()

    if not is_youtube_url(url):
        console.print(f"[bold red]Not a recognised YouTube URL: {url}[/bold red]")
        raise SystemExit(1)

    movie_path = download_from_youtube(url, config, max_height=quality, auto_confirm=yes)

    if prompt:
        params = parse_natural_prompt(prompt)
        if language:
            params.language = language
        if duration:
            params.duration_minutes = duration
        if style:
            params.narration_style = style
    else:
        params = ExplanationParams(
            language=language or config.get("narration.default_language", "en"),
            duration_minutes=duration or config.get("story.default_duration_minutes", 20),
            narration_style=style or config.get("narration.default_style", "cinematic_storytelling"),
        )

    orchestrator = StudioOrchestrator(movie_path, config, params)
    orchestrator.run_pipeline(resume_mode=False)


@cli.command("run")
@click.option("--prompt", "-p", default=None, help="One-line natural prompt")
@click.option("--input", "-i", "input_file", default=None, help="Input movie file path OR YouTube URL")
@click.option("--language", "-l", default=None, help="Language (en, bn, hi)")
@click.option("--duration", "-d", default=None, type=int, help="Duration in minutes")
@click.option("--style", "-s", default=None, help="Narration style")
@click.option("--review", is_flag=True, default=False, help="Open interactive script review and voice audition screen")
@click.option("--auto-approve", "-y", "auto_approve", is_flag=True, default=False, help="Auto-approve script and voice preview")
@click.option("--resume/--no-resume", default=True, help="Resume from cached completed stages if available")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
def run_cmd(prompt, input_file, language, duration, style, review, auto_approve, resume, config_file):
    """Execute movie explanation generation."""
    config = Config(config_file)
    setup_logger()

    movie_path = None
    if input_file:
        if is_youtube_url(input_file):
            movie_path = download_from_youtube(input_file, config, auto_confirm=auto_approve)
        elif os.path.isfile(input_file):
            movie_path = input_file
        else:
            console.print(f"[bold red]File not found and not a URL: {input_file}[/bold red]")
            sys.exit(1)

    movie_path = movie_path or find_input_movie(config.input_dir)
    if not movie_path:
        console.print(f"[bold red]No movie file specified or found in {config.input_dir}[/bold red]")
        sys.exit(1)

    if prompt:
        params = parse_natural_prompt(prompt)
    else:
        params = ExplanationParams(
            language=language or "en",
            duration_minutes=duration or 20,
            narration_style=style or "cinematic_storytelling"
        )

    interactive_mode = review or (not auto_approve and not prompt and sys.stdin.isatty())
    orchestrator = StudioOrchestrator(movie_path, config, params)
    orchestrator.run_pipeline(
        resume_mode=resume,
        interactive_approval=interactive_mode,
        auto_approve=auto_approve or (not interactive_mode)
    )


@cli.command("review")
@click.option("--input", "-i", "input_file", default=None, help="Input movie file path")
@click.option("--language", "-l", default="en", help="Language code (en, bn, hi)")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
def review_cmd(input_file, language, config_file):
    """Review, edit, and approve the explanation script and pronunciation dictionary."""
    config = Config(config_file)
    setup_logger()
    movie_path = input_file or find_input_movie(config.input_dir)
    if not movie_path:
        console.print(f"[bold red]No movie found in {config.input_dir}[/bold red]")
        sys.exit(1)

    params = ExplanationParams(language=language)
    orchestrator = StudioOrchestrator(movie_path, config, params)
    script_manifest_path = orchestrator.project.get_path("scripts", f"script_{language}_manifest.json")

    if not os.path.isfile(script_manifest_path):
        console.print(f"[bold yellow]Script manifest not found at {script_manifest_path}. Generating initial script...[/bold yellow]")
        orchestrator.run_pipeline(resume_mode=True, auto_approve=True)

    script_ver = orchestrator.script_reviewer.load_script_version(script_manifest_path)
    orchestrator._run_interactive_script_review(script_ver, script_manifest_path)


@cli.command("audition")
@click.option("--input", "-i", "input_file", default=None, help="Input movie file path")
@click.option("--language", "-l", default="en", help="Language code (en, bn, hi)")
@click.option("--voice", "-v", default=None, help="Specific Voice ID to audition")
@click.option("--provider", "-p", default="auto", help="Voice engine provider (gemini, google_cloud, edge-tts, system)")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
def audition_cmd(input_file, language, voice, provider, config_file):
    """Audition narrator voices across Normal, Suspense, and Emotional passages."""
    config = Config(config_file)
    setup_logger()
    movie_path = input_file or find_input_movie(config.input_dir)
    if not movie_path:
        console.print(f"[bold red]No movie found in {config.input_dir}[/bold red]")
        sys.exit(1)

    params = ExplanationParams(language=language)
    orchestrator = StudioOrchestrator(movie_path, config, params)
    script_manifest_path = orchestrator.project.get_path("scripts", f"script_{language}_manifest.json")
    script_ver = orchestrator.script_reviewer.load_script_version(script_manifest_path) if os.path.isfile(script_manifest_path) else ScriptVersion("draft", language, "cinematic", 20, 0, 0)
    voice_approval_path = orchestrator.project.get_path("narration", "preview_approval.json")

    from app.tts.google_adapters import get_voice_adapter
    adapter = get_voice_adapter(provider)
    voice_id = voice or (adapter.list_voices(language)[0]["id"] if adapter.list_voices(language) else "default")

    voice_cfg = VoiceConfiguration(
        provider=adapter.name,
        model=getattr(adapter, "model", "default"),
        voice_id=voice_id,
        language=language,
        speaking_rate=float(config.get("narration.speed", 1.0))
    )
    orchestrator._run_interactive_voice_audition(script_ver, voice_cfg, voice_approval_path)


@cli.command("synthesize")
@click.option("--input", "-i", "input_file", default=None, help="Input movie file path")
@click.option("--language", "-l", default="en", help="Language code (en, bn, hi)")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
def synthesize_cmd(input_file, language, config_file):
    """Synthesize full narration audio after script and voice preview approvals."""
    config = Config(config_file)
    setup_logger()
    movie_path = input_file or find_input_movie(config.input_dir)
    if not movie_path:
        console.print(f"[bold red]No movie found in {config.input_dir}[/bold red]")
        sys.exit(1)

    params = ExplanationParams(language=language)
    orchestrator = StudioOrchestrator(movie_path, config, params)
    script_manifest_path = orchestrator.project.get_path("scripts", f"script_{language}_manifest.json")
    script_ver = orchestrator.script_reviewer.load_script_version(script_manifest_path)

    if not orchestrator.script_reviewer.is_approved(script_ver):
        console.print(f"[bold red]Script version '{script_ver.script_version_id}' is not approved. Run 'python main.py review' first.[/bold red]")
        sys.exit(1)

    from app.tts.pipeline import synthesize_script_narration
    voice_approval_path = orchestrator.project.get_path("narration", "preview_approval.json")
    approval = orchestrator.voice_audition_mgr.load_preview_approval(voice_approval_path)
    voice_id = approval.voice_id if approval else None

    console.print(f"[bold green]Synthesizing narration for approved script {script_ver.script_version_id}...[/bold green]")
    manifest = synthesize_script_narration(
        script_manifest=script_ver.to_dict(),
        output_dir=orchestrator.project.dirs["narration"],
        tts_provider=orchestrator.voice_adapter,
        speed=float(config.get("narration.speed", 1.0)),
        voice_id=voice_id
    )
    console.print(f"[bold green]Narration synthesized successfully:[/bold green] {manifest['full_narration_file']}")


@cli.command("resume")
@click.option("--input", "-i", "input_file", default=None, help="Input movie file path")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
def resume_cmd(input_file, config_file):
    """Resume an interrupted processing task from the last completed stage."""
    config = Config(config_file)
    movie_path = input_file or find_input_movie(config.input_dir)
    if not movie_path:
        console.print(f"[bold red]No movie found in {config.input_dir}[/bold red]")
        sys.exit(1)

    orchestrator = StudioOrchestrator(movie_path, config)
    orchestrator.run_pipeline(resume_mode=True)


@cli.command("inspect")
@click.option("--input", "-i", "input_file", default=None, help="Input movie file path")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
def inspect_cmd(input_file, config_file):
    """Inspect media file streams, codecs, subtitles, and audio tracks."""
    config = Config(config_file)
    movie_path = input_file or find_input_movie(config.input_dir)
    if not movie_path:
        console.print(f"[bold red]No movie found in {config.input_dir}[/bold red]")
        sys.exit(1)

    info = probe_media_file(movie_path)
    table = Table(title=f"Media Inspection: {os.path.basename(movie_path)}")
    table.add_column("Property", style="cyan")
    table.add_column("Details", style="white")

    table.add_row("Duration", f"{info['duration_seconds']:.1f}s")
    table.add_row("Resolution", f"{info['video']['resolution']} ({info['video']['fps']} fps)")
    table.add_row("Video Codec", info['video']['codec'])
    table.add_row("Audio Tracks", f"{info['audio']['streams_count']} (Codecs: {info['audio']['codec']}, Langs: {', '.join(info['audio']['languages'])})")
    table.add_row("Subtitle Streams", f"{info['subtitles']['streams_count']} (Langs: {', '.join(info['subtitles']['languages']) or 'None'})")
    table.add_row("File Size", f"{info['file_size_mb']} MB")

    console.print(table)


@cli.command("status")
@click.option("--input", "-i", "input_file", default=None, help="Input movie file path")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
def status_cmd(input_file, config_file):
    """Check pipeline stage status and progress for a movie project."""
    config = Config(config_file)
    movie_path = input_file or find_input_movie(config.input_dir)
    if not movie_path:
        console.print(f"[bold red]No movie found in {config.input_dir}[/bold red]")
        sys.exit(1)

    orchestrator = StudioOrchestrator(movie_path, config)
    summary = orchestrator.state.get_progress_summary()

    table = Table(title=f"Project Progress: {orchestrator.project.movie_filename}")
    table.add_column("Stage", style="cyan")
    table.add_column("Status", style="bold")

    status_colors = {
        "completed": "[green]COMPLETED[/green]",
        "in_progress": "[yellow]IN PROGRESS[/yellow]",
        "pending": "[dim]PENDING[/dim]",
        "failed": "[bold red]FAILED[/bold red]"
    }

    for stage, st in summary["stages"].items():
        table.add_row(stage, status_colors.get(st, st))

    console.print(table)
    console.print(f"\n[bold]Overall Completion:[/bold] {summary['percentage']}% ({summary['completed_stages']}/{summary['total_stages']} stages)")


@cli.command("clean")
@click.option("--config", "-c", "config_file", default="config.yaml", help="Path to config.yaml")
def clean_cmd(config_file):
    """Clean temporary cache and rendering workspace files."""
    config = Config(config_file)
    temp_dir = config.temp_dir
    count = 0
    if os.path.isdir(temp_dir):
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)
        count += 1
    console.print(f"[green]Cleaned temporary cache files in {temp_dir}.[/green]")


if __name__ == "__main__":
    cli()
