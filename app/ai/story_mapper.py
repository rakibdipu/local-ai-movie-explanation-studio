"""Global Master Story Map reconstruction and narrative arc synthesis."""

import os
from typing import List, Dict, Any, Optional
from app.ai.provider import AIProvider, LocalHeuristicAIProvider
from app.core.logger import get_logger
from app.utils.files import safe_write_json

logger = get_logger()


def build_master_story_map(
    chunk_analyses: List[Dict[str, Any]],
    output_path: str,
    ai_provider: AIProvider,
    story_research: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Synthesize chunk analyses and online research into a unified global master story map."""
    logger.info("Constructing Master Story Map across full narrative timeline...")

    research = story_research or {}
    total_chunks = len(chunk_analyses)
    all_characters = set()
    for ca in chunk_analyses:
        for ch in ca.get("characters", []):
            all_characters.add(ch)

    # Add researched characters
    for r_ch in research.get("characters", []):
        c_name = r_ch.get("character") or r_ch.get("name")
        if c_name:
            all_characters.add(c_name)


    if not isinstance(ai_provider, LocalHeuristicAIProvider):
        # Prepare condensed overview of all chunks for global synthesis
        chunks_summary_lines = []
        for ca in chunk_analyses:
            chunks_summary_lines.append(
                f"[{ca['start']} - {ca['end']}] (Importance: {ca['importance']}): {ca['summary']}"
            )
        condensed_timeline = "\n".join(chunks_summary_lines)

        prompt = f"""
You are a master story architect and dramaturg. Based on the following chronological chunk summaries of a complete movie, build a comprehensive Master Story Map.

Timeline of Chunks:
{condensed_timeline[:4000]}

Known Characters: {', '.join(sorted(list(all_characters))) if all_characters else 'To be identified from story'}

Return ONLY a JSON object with this exact structure:
{{
  "logline": "1-2 sentence core premise and stakes of the entire movie",
  "setup": [
    {{"time": "00:00:00", "description": "Opening world setup and protagonist introduction"}}
  ],
  "characters": [
    {{"name": "Name", "role": "Protagonist / Antagonist / Ally", "arc": "Brief description of their character journey"}}
  ],
  "inciting_incident": [
    {{"time": "00:10:00", "description": "The event that sets the story in motion"}}
  ],
  "major_conflicts": [
    {{"time": "00:25:00", "description": "Primary obstacles and escalating tensions"}}
  ],
  "investigation": [
    {{"time": "00:45:00", "description": "Rising action, discoveries, search for truth or survival"}}
  ],
  "reveals": [
    {{"time": "01:10:00", "description": "Major plot twists, revelations, or betrayal"}}
  ],
  "climax": [
    {{"time": "01:25:00", "description": "The decisive final confrontation or turning point"}}
  ],
  "resolution": [
    {{"time": "01:40:00", "description": "The aftermath, final consequences, and conclusion"}}
  ]
}}
"""
        system_prompt = "You are a senior cinematic screenwriter and story analyst. Output valid JSON only."
        try:
            story_map = ai_provider.generate_json(prompt, system_prompt)
            if "climax" in story_map and "setup" in story_map:
                safe_write_json(output_path, story_map)
                logger.info(f"Master story map generated via AI and saved to {output_path}")
                return story_map
        except Exception as e:
            logger.warning(f"AI Master Story Map generation fallback: {e}")

    # Heuristic narrative arc division (Classic 3-Act Structure)
    setup_idx = max(1, int(total_chunks * 0.15))
    inciting_idx = max(setup_idx, int(total_chunks * 0.25))
    midpoint_idx = max(inciting_idx, int(total_chunks * 0.50))
    reveal_idx = max(midpoint_idx, int(total_chunks * 0.70))
    climax_idx = max(reveal_idx, int(total_chunks * 0.85))

    logline = research.get("plot", "")
    if logline:
        # First 2 sentences
        sentences = [s.strip() for s in logline.split(".") if s.strip()]
        logline_text = ". ".join(sentences[:2]) + "."
    else:
        logline_text = "An engaging cinematic story following distinct characters facing dramatic conflicts and revelations."

    # Build character list
    char_list = []
    for r_c in research.get("characters", [])[:6]:
        char_list.append({
            "name": r_c.get("character", "Character"),
            "actor": r_c.get("actor", ""),
            "role": r_c.get("description", "Key Character"),
            "arc": f"Played by {r_c.get('actor', '')}. Key figure in the movie's events."
        })

    if not char_list:
        char_list = [
            {"name": c, "role": "Key Character", "arc": "Navigates the evolving events of the story."}
            for c in sorted(list(all_characters))[:5]
        ] or [{"name": "Protagonist", "role": "Main Lead", "arc": "Faces the central conflict and choices."}]

    story_map = {
        "movie_title": research.get("title", "Feature Film"),
        "logline": logline_text,
        "setup": [
            {
                "time": chunk_analyses[0]["start"] if total_chunks > 0 else "00:00:00",
                "description": research.get("plot", chunk_analyses[0]["summary"])[:300] if total_chunks > 0 else "The story introduces the main environment and central figures."
            }
        ],
        "characters": char_list,
        "inciting_incident": [
            {
                "time": chunk_analyses[min(inciting_idx, total_chunks - 1)]["start"] if total_chunks > 0 else "00:15:00",
                "description": f"A major conflict erupts involving {research.get('lead_protagonist', 'the protagonist')}, destabilizing normalcy."
            }
        ],

        "major_conflicts": [
            {
                "time": chunk_analyses[min(midpoint_idx, total_chunks - 1)]["start"] if total_chunks > 0 else "00:35:00",
                "description": chunk_analyses[min(midpoint_idx, total_chunks - 1)]["summary"] if total_chunks > 0 else "Stakes escalate as challenges mount."
            }
        ],
        "investigation": [
            {
                "time": chunk_analyses[min(reveal_idx - 1, total_chunks - 1)]["start"] if total_chunks > 0 else "00:50:00",
                "description": "Characters pursue answers and confront growing challenges."
            }
        ],
        "reveals": [
            {
                "time": chunk_analyses[min(reveal_idx, total_chunks - 1)]["start"] if total_chunks > 0 else "01:10:00",
                "description": chunk_analyses[min(reveal_idx, total_chunks - 1)]["summary"] if total_chunks > 0 else "Shocking revelations come to light."
            }
        ],
        "climax": [
            {
                "time": chunk_analyses[min(climax_idx, total_chunks - 1)]["start"] if total_chunks > 0 else "01:25:00",
                "description": chunk_analyses[min(climax_idx, total_chunks - 1)]["summary"] if total_chunks > 0 else "The decisive confrontation reaches its peak."
            }
        ],
        "resolution": [
            {
                "time": chunk_analyses[-1]["start"] if total_chunks > 0 else "01:40:00",
                "description": chunk_analyses[-1]["summary"] if total_chunks > 0 else "The final outcome settles the fates of the characters."
            }
        ]
    }

    safe_write_json(output_path, story_map)
    logger.info(f"Master story map synthesized and saved to {output_path}")
    return story_map
