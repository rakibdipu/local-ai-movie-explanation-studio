"""Chunk-level story comprehension and narrative significance scoring."""

import os
import re
from typing import List, Dict, Any, Optional
from app.ai.provider import AIProvider, LocalHeuristicAIProvider
from app.core.logger import get_logger
from app.utils.files import safe_write_json
from app.utils.timecode import seconds_to_hms

logger = get_logger()


def extract_characters_heuristic(transcript: str) -> List[str]:
    """Extract candidate character names from transcript dialogue patterns."""
    # Look for capitalized proper nouns following greetings, verbs, or speaker cues
    names = set()
    patterns = [
        r"\b(?:Hey|Hi|Hello|Mr\.|Mrs\.|Ms\.|Dr\.|Detective|Officer|Captain)\s+([A-Z][a-z]+)\b",
        r"\b([A-Z][a-z]+),\s+(?:listen|look|what|where|why|how|come|stop)\b",
        r"\b(?:I am|my name is|this is|call me)\s+([A-Z][a-z]+)\b",
    ]
    for p in patterns:
        for match in re.finditer(p, transcript):
            names.add(match.group(1))

    # Clean out false positives
    common_words = {"God", "Sir", "Please", "Wait", "Look", "Listen", "Yes", "No", "Well", "Right", "Okay", "Oh", "Ah"}
    return sorted(list(names - common_words))


def calculate_chunk_importance_heuristic(cues: List[Dict[str, Any]], chunk_index: int, total_chunks: int) -> float:
    """Calculate heuristic narrative importance based on keywords, position, and dialogue density."""
    if not cues:
        # Action/visual sequence: beginning and ending chunks get high importance
        if chunk_index == 0 or chunk_index >= total_chunks - 2:
            return 0.85
        return 0.60

    score = 0.50
    # Position weight: beginning (setup) and end (climax/resolution) are critical
    pos_ratio = chunk_index / max(1, total_chunks - 1)
    if pos_ratio <= 0.15:  # Hook / Setup
        score += 0.25
    elif pos_ratio >= 0.75:  # Climax / Ending
        score += 0.30
    elif 0.40 <= pos_ratio <= 0.60:  # Midpoint twist
        score += 0.15

    # Narrative keyword triggers
    all_text = " ".join(c["text"].lower() for c in cues)
    high_impact_keywords = [
        "kill", "death", "murder", "secret", "truth", "discover", "police", "gun",
        "evidence", "father", "mother", " betrayed", "money", "blood", "run", "trap",
        "love", "hate", "found", "why did you", "it was you", "remember", "help me"
    ]
    matches = sum(1 for kw in high_impact_keywords if kw in all_text)
    score += min(0.20, matches * 0.04)

    return round(min(1.0, max(0.2, score)), 2)


def analyze_single_chunk(chunk: Dict[str, Any], chunk_index: int, total_chunks: int, ai_provider: AIProvider) -> Dict[str, Any]:
    """Analyze a single movie chunk using AI provider with structured JSON extraction."""
    chunk_id = chunk["chunk_id"]
    start_str = seconds_to_hms(chunk["start"])
    end_str = seconds_to_hms(chunk["end"])
    transcript = chunk.get("transcript", "")
    cues = chunk.get("cues", [])

    if not isinstance(ai_provider, LocalHeuristicAIProvider):
        prompt = f"""
You are an expert film analyst. Analyze the following movie chunk dialogue:
Time window: {start_str} to {end_str} (Chunk #{chunk_id} of {total_chunks})

Transcript:
{transcript[:2500]}

Provide a structured JSON response with the following fields:
{{
  "chunk_id": {chunk_id},
  "start": "{start_str}",
  "end": "{end_str}",
  "summary": "Concise 2-3 sentence summary of what happens in this scene",
  "characters": ["List of character names active or mentioned"],
  "location": "Probable location or setting",
  "events": ["Key plot events or actions in order"],
  "conflict": "Primary tension, dilemma, or dispute",
  "revelations": ["Any new clues, backstory, or secrets revealed"],
  "emotional_tone": "e.g. suspenseful, romantic, tense, mysterious, melancholic",
  "importance": 0.85
}}
"""
        system_prompt = "You are a senior film story analyst. Return ONLY valid JSON."
        try:
            res_json = ai_provider.generate_json(prompt, system_prompt)
            if "summary" in res_json:
                res_json["chunk_id"] = chunk_id
                res_json["start"] = start_str
                res_json["end"] = end_str
                res_json["start_seconds"] = chunk["start"]
                res_json["end_seconds"] = chunk["end"]
                return res_json
        except Exception as e:
            logger.warning(f"AI chunk analysis fallback for chunk {chunk_id}: {e}")

    # Heuristic analysis engine
    chars = extract_characters_heuristic(transcript)
    importance = calculate_chunk_importance_heuristic(cues, chunk_index, total_chunks)
    
    # Generate concise summary from dialogue — keep it language-neutral (timecodes only)
    # The actual narration language is applied in script_writer.py, not here.
    sample_dialogues = [c["text"] for c in cues[:4]]
    if sample_dialogues:
        # Use a short neutral description; the heuristic script writer uses its own
        # localized sentences and does NOT embed this English summary for bn/hi.
        dialogue_preview = " / ".join(d[:60] for d in sample_dialogues[:2])
        summary = f"Scene {start_str}-{end_str}: {dialogue_preview}"
    else:
        summary = f"Scene {start_str}-{end_str}: visual/atmospheric sequence."

    return {
        "chunk_id": chunk_id,
        "start": start_str,
        "end": end_str,
        "start_seconds": chunk["start"],
        "end_seconds": chunk["end"],
        "summary": summary,
        "characters": chars,
        "location": "Key Story Setting",
        "events": [f"Scene development around {start_str}"],
        "conflict": "Narrative tension unfolds in this sequence.",
        "revelations": [],
        "emotional_tone": "dramatic",
        "importance": importance
    }


def analyze_all_chunks(
    chunks: List[Dict[str, Any]],
    output_dir: str,
    ai_provider: AIProvider
) -> List[Dict[str, Any]]:
    """Process all narrative chunks and save individual + master chunk analyses."""
    os.makedirs(output_dir, exist_ok=True)
    chunks_sub_dir = os.path.join(output_dir, "chunks")
    os.makedirs(chunks_sub_dir, exist_ok=True)

    analyzed_chunks = []
    total = len(chunks)

    logger.info(f"Analyzing {total} story chunks for narrative causality and importance...")
    for idx, chunk in enumerate(chunks):
        analysis = analyze_single_chunk(chunk, idx, total, ai_provider)
        analyzed_chunks.append(analysis)

        # Save individual chunk file
        chunk_file = os.path.join(chunks_sub_dir, f"chunk_{chunk['chunk_id']:03d}.json")
        safe_write_json(chunk_file, analysis)

    # Save consolidated chunk analysis
    master_chunk_file = os.path.join(output_dir, "chunk_analysis.json")
    safe_write_json(master_chunk_file, analyzed_chunks)
    logger.info(f"Chunk analysis complete. Saved to {master_chunk_file}")

    return analyzed_chunks
