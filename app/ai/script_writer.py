"""Explanation script generation and pacing management for YouTube movie breakdowns."""

import os
import re
import json
from typing import List, Dict, Any, Optional
from app.ai.provider import AIProvider, LocalHeuristicAIProvider
from app.ai.translator import get_language_template
from app.core.logger import get_logger
from app.utils.files import safe_write_json
from app.utils.timecode import seconds_to_hms

logger = get_logger()


def calculate_target_word_count(duration_minutes: int, language: str = "en", words_per_minute: Optional[int] = None) -> int:
    """Calculate target total words to match desired spoken duration."""
    if words_per_minute is None:
        rates = {"en": 145, "bn": 135, "hi": 140}
        words_per_minute = rates.get(language.lower(), 140)
    raw = int(duration_minutes * words_per_minute)
    # Clamp: at least 100 words (avoids empty scripts), but don't inflate short targets.
    return max(100, raw)


def generate_explanation_script(
    master_story: Dict[str, Any],
    chunk_analyses: List[Dict[str, Any]],
    target_duration_minutes: int,
    language: str,
    narration_style: str,
    output_dir: str,
    ai_provider: AIProvider,
    story_research: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Generate human-like structured explanation script matching target duration and style."""
    os.makedirs(output_dir, exist_ok=True)
    lang_code = language.lower()
    target_words = calculate_target_word_count(target_duration_minutes, lang_code)
    template = get_language_template(lang_code)


    logger.info(
        f"Generating {target_duration_minutes}-minute {lang_code.upper()} explanation script "
        f"(Target ~{target_words} words, Style: {narration_style})..."
    )

    # Calculate optimal segment count (~24 seconds per narration segment)
    target_total_sec = target_duration_minutes * 60
    segment_duration_target_sec = 24.0
    num_segments = max(6, int(round(target_total_sec / segment_duration_target_sec)))

    segments = []

    if not isinstance(ai_provider, LocalHeuristicAIProvider):
        # AI Generation Prompt
        story_summary = json.dumps(master_story, indent=2, ensure_ascii=False)
        prompt = f"""
You are a master YouTube movie recap storyteller (like CineBuzz, Movie Recaps, Mystery Recapped) writing a gripping {target_duration_minutes}-minute explanation script in {lang_code.upper()}.
Target Word Count: ~{target_words} words.
Narration Style: {narration_style.replace('_', ' ').title()}.

Master Story Map:
{story_summary[:3500]}

ESSENTIAL STORYTELLING RULES (CINEBUZZ / VIRAL RECAP FORMULA):
1. **Engaging Psychological Hook**: Start the first segment with a philosophical or psychological reflection on human nature or ordinary life turning into crime/survival, then introduce the protagonist's normal world before the descent.
2. **Character Banter, Romance & Heart**: Do NOT skip personal moments. Include the protagonist's love story, romantic proposals, humorous banter between friends, and family devotion.
3. **Direct Dialogues & Punchlines**: Dramatize key character dialogues with punchy direct speech in quotation marks or spoken form. Make characters feel alive.
4. **Explain Tactical Details & Clever Schemes**: Clearly explain HOW plans, tricks, heists, or deceptions worked (e.g. decoys, hidden compartments, misdirection). Audiences love the intelligence behind moves.
5. **Zero Robotic Cliches**: NEVER use boring filler phrases like "সিনেমার শুরুতে দেখা যায়", "পর্দায় এবার ভেসে ওঠে", "দৃশ্যপট এবার সরে আসে", "এদিকে গল্পের পরবর্তী ধাপে". Use natural, seamless storytelling transitions.
6. **Emotional Climax & Twists**: Build intense emotional stakes around family protection and revenge, ending with the true mastermind twist and satisfying payoff.
7. **Pacing & Length**: Structure into approximately {num_segments} distinct narration segments following: Hook -> Setup -> Inciting Incident -> Escalation -> Revelations -> Climax -> Resolution -> Outro.
8. Return ONLY a valid JSON list of segments with this structure:
[
  {{
    "segment_id": 1,
    "act": "hook",
    "narration_text": "Spoken text in {lang_code.upper()}...",
    "source_time_reference": "00:00:00 - 00:02:30",
    "estimated_seconds": 25.0
  }}
]
"""
        system_prompt = f"You are a top-tier YouTube cinematic movie recap narrator specializing in high-retention, emotionally gripping scripts in {lang_code.upper()}. Return ONLY valid JSON."
        try:
            res_json = ai_provider.generate_json(prompt, system_prompt)
            if isinstance(res_json, list) and len(res_json) >= 4:
                segments = res_json
                logger.info(f"Generated {len(segments)} narration segments via AI Provider.")
        except Exception as e:
            logger.warning(f"AI script generation fallback: {e}")

    # Heuristic Script Generator Fallback
    if not segments:
        segments = _generate_heuristic_script(
            master_story=master_story,
            chunk_analyses=chunk_analyses,
            num_segments=num_segments,
            target_words=target_words,
            language=lang_code,
            style=narration_style,
            template=template,
            story_research=story_research
        )


    from app.core.models import DeliveryProfile, ScriptVersion, NarrationSegment

    ACT_EMOTION_MAP = {
        "hook": DeliveryProfile.MYSTERY,
        "setup": DeliveryProfile.NORMAL_CONVERSATION,
        "inciting_incident": DeliveryProfile.SUSPENSE,
        "investigation": DeliveryProfile.MYSTERY,
        "escalation": DeliveryProfile.ACTION,
        "revelations": DeliveryProfile.EMOTIONAL_REVELATION,
        "climax": DeliveryProfile.CLIMAX,
        "resolution": DeliveryProfile.RESOLUTION
    }

    # Normalize segment timings, emotions, and word counts
    total_words = 0
    total_estimated_sec = 0.0
    full_script_lines = []
    clean_script_lines = []
    direction_script_lines = []

    # Calculate movie total duration to map timeline evenly
    total_movie_sec = 3600.0
    if chunk_analyses:
        last_ca = chunk_analyses[-1]
        total_movie_sec = float(last_ca.get("end_seconds") or last_ca.get("end") or 3600.0)
    sec_per_segment_source = total_movie_sec / max(1, len(segments))

    # Build initial pronunciation dictionary from story research and characters
    pronunciation_dictionary = {}
    research = story_research or {}
    for ch in research.get("characters", []):
        c_name = ch.get("character") or ch.get("name")
        if c_name:
            pronunciation_dictionary[c_name] = c_name
    for ch in master_story.get("characters", []):
        c_name = ch.get("name") if isinstance(ch, dict) else ch
        if c_name and c_name not in pronunciation_dictionary:
            pronunciation_dictionary[c_name] = c_name

    for idx, seg in enumerate(segments):
        seg["segment_id"] = idx + 1
        text = seg.get("narration_text", "").strip()
        words = len(text.split())
        total_words += words

        # Speech rate ~2.3 words per second (138 wpm)
        est_sec = max(5.0, round(words / 2.3, 1))
        seg["estimated_seconds"] = est_sec
        total_estimated_sec += est_sec

        # Source time mapping
        if seg.get("source_start_seconds") is None:
            src_start = round(idx * sec_per_segment_source, 2)
            src_end = round(min(total_movie_sec, (idx + 1) * sec_per_segment_source), 2)
            seg["source_start_seconds"] = src_start
            seg["source_end_seconds"] = src_end
            seg["source_time_reference"] = f"{seconds_to_hms(src_start)} - {seconds_to_hms(src_end)}"
        else:
            src_start = seg["source_start_seconds"]
            src_end = seg["source_end_seconds"]
            if not seg.get("source_time_reference"):
                seg["source_time_reference"] = f"{seconds_to_hms(src_start)} - {seconds_to_hms(src_end)}"

        # Assign delivery profile and pacing
        act_key = seg.get("act", "scene").lower()
        emotion = seg.get("emotion") or ACT_EMOTION_MAP.get(act_key, DeliveryProfile.NORMAL_CONVERSATION)
        prof = DeliveryProfile.get_profile(emotion)
        seg["emotion"] = emotion
        seg["pacing"] = float(seg.get("pacing", prof["pacing"]))
        seg["delivery_notes"] = seg.get("delivery_notes") or prof["description"]
        seg["pronunciation_notes"] = seg.get("pronunciation_notes", "Standard native pronunciation")
        seg["clean_text"] = text
        seg["audio_status"] = "pending"

        full_script_lines.append(f"[{seg.get('act', 'scene').upper()}] ({seg['source_time_reference']})\n{text}\n")
        clean_script_lines.append(text)
        direction_script_lines.append(
            f"Segment #{seg['segment_id']} [{seg.get('act', 'scene').upper()}] ({seg['source_time_reference']})\n"
            f"Emotion: {emotion} | Pace: {seg['pacing']:.2f}x\n"
            f"Direction: {seg['delivery_notes']}\n"
            f"Narration: {text}\n"
        )

    # Instantiate typed script version
    typed_segments = [NarrationSegment.from_dict(s) for s in segments]
    script_version = ScriptVersion(
        script_version_id="draft",
        language=lang_code,
        style=narration_style,
        target_duration_minutes=target_duration_minutes,
        total_words=total_words,
        total_segments=len(segments),
        segments=typed_segments,
        approval_status="draft",
        pronunciation_dictionary=pronunciation_dictionary
    )
    script_version.content_hash = script_version.calculate_content_hash()

    manifest = script_version.to_dict()
    manifest["total_estimated_seconds"] = round(total_estimated_sec, 1)

    # Save manifest and plain text scripts
    manifest_path = os.path.join(output_dir, f"script_{lang_code}_manifest.json")
    script_txt_path = os.path.join(output_dir, f"script_{lang_code}.txt")
    clean_txt_path = os.path.join(output_dir, f"script_{lang_code}_clean.txt")
    direction_txt_path = os.path.join(output_dir, f"script_{lang_code}_direction.txt")

    safe_write_json(manifest_path, manifest)

    with open(script_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(full_script_lines))

    with open(clean_txt_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(clean_script_lines))

    with open(direction_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(direction_script_lines))

    logger.info(
        f"Script generated: {len(segments)} segments, {total_words} words, "
        f"~{int(total_estimated_sec // 60)}m {int(total_estimated_sec % 60)}s. "
        f"Saved to {manifest_path} (Clean script: {clean_txt_path})"
    )

    return manifest


def _generate_heuristic_script(
    master_story: Dict[str, Any],
    chunk_analyses: List[Dict[str, Any]],
    num_segments: int,
    target_words: int,
    language: str,
    style: str,
    template: Dict[str, Any],
    story_research: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Build a rich, structured story explanation script with full 20-minute depth and verified movie details."""
    research = story_research or {}
    title = research.get("title") or master_story.get("movie_title") or "Movie"
    article_title = research.get("article_title", "")
    full_text = f"{title} {article_title}".lower()

    words_per_segment = max(55, target_words // max(1, num_segments))

    # 1. First, check curated movie beats registry for verified scene beats
    from app.ai.movie_beats import get_movie_beats
    curated_beats = get_movie_beats(full_text, language)

    if curated_beats:
        logger.info(f"Using {len(curated_beats)} verified scene beats for '{title}' ({language.upper()})")
        return _format_beats_into_segments(
            narrative_beats=curated_beats,
            num_segments=num_segments,
            language=language
        )

    # 2. Dynamic story script synthesis from research, master_story & chunk_analyses
    logger.info(f"Synthesizing dynamic story script for '{title}' from plot research and scene chunks")
    return _build_dynamic_story_script(
        title=title,
        research=research,
        master_story=master_story,
        chunk_analyses=chunk_analyses,
        num_segments=num_segments,
        words_per_segment=words_per_segment,
        language=language,
        template=template
    )


def _format_beats_into_segments(
    narrative_beats: List[Any],
    num_segments: int,
    language: str
) -> List[Dict[str, Any]]:
    """Format and distribute narrative beats evenly across the requested segment count."""
    total_beats = len(narrative_beats)
    if num_segments >= total_beats:
        selected_indices = list(range(total_beats))
    else:
        step = (total_beats - 1) / max(1, num_segments - 1)
        selected_indices = [int(round(i * step)) for i in range(num_segments)]

    seen_texts = set()
    segments = []
    prefix = {
        "en": "Continuing our journey through the story, ",
        "bn": "এদিকে গল্পের পরবর্তী ধাপে, ",
        "hi": "कहानी के अगले मोड़ पर, "
    }.get(language, "")

    for idx, b_idx in enumerate(selected_indices):
        beat_item = narrative_beats[b_idx]
        if len(beat_item) >= 4:
            act, text, b_start, b_end = beat_item[:4]
        else:
            act, text = beat_item[:2]
            b_start = None
            b_end = None

        if text in seen_texts:
            text = f"{prefix}{text}"
        seen_texts.add(text)
        seg = {
            "segment_id": idx + 1,
            "act": act,
            "narration_text": text,
            "curated": True,
            "explicit_window": True
        }
        if b_start is not None and b_end is not None:
            seg["source_start_seconds"] = float(b_start)
            seg["source_end_seconds"] = float(b_end)
            seg["source_time_reference"] = f"{seconds_to_hms(b_start)} - {seconds_to_hms(b_end)}"
        segments.append(seg)

    return segments


def _build_dynamic_story_script(
    title: str,
    research: Dict[str, Any],
    master_story: Dict[str, Any],
    chunk_analyses: List[Dict[str, Any]],
    num_segments: int,
    words_per_segment: int,
    language: str,
    template: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Synthesize a dynamic, movie-specific 8-act explanation script from plot research and scene chunks."""
    plot_text = research.get("plot", "").strip() or master_story.get("logline", "").strip()
    characters = research.get("characters", []) or master_story.get("characters", [])
    char_names = [c.get("character") or c.get("name") for c in characters if c.get("character") or c.get("name")]
    main_char = char_names[0] if char_names else "our protagonist"

    # Split plot into narrative sentences
    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", plot_text) if len(s.strip()) > 15]

    act_order = [
        "hook", "setup", "inciting_incident", "investigation",
        "escalation", "revelations", "climax", "resolution"
    ]

    segments = []
    total_chunks = len(chunk_analyses)

    for idx in range(num_segments):
        progress = idx / max(1, num_segments - 1)
        act_idx = min(len(act_order) - 1, int(progress * len(act_order)))
        act = act_order[act_idx]

        # Pick matching plot sentence if available
        plot_sentence = ""
        if raw_sentences:
            s_idx = min(len(raw_sentences) - 1, int(progress * len(raw_sentences)))
            plot_sentence = raw_sentences[s_idx]

        # Pick matching chunk analysis if available
        chunk_info = ""
        if total_chunks > 0:
            c_idx = min(total_chunks - 1, int(progress * total_chunks))
            chunk = chunk_analyses[c_idx]
            summary = chunk.get("summary", "")
            if summary and not summary.startswith("Scene "):
                chunk_info = summary

        # Formulate narration text based on language
        if language == "bn":
            if act == "hook":
                text = f"আজকের রোমাঞ্চকর সিনেমা '{title}'-এর শুরুতে আমরা এক অবিশ্বাস্য নাটকীয় দৃশ্য দেখতে পাই। {plot_sentence}"
            elif act == "resolution":
                text = f"গল্পের সমাপ্তিতে সমস্ত অন্যায় চূর্ণবিচূর্ণ হয়ে শান্তি ফিরে আসে। {plot_sentence} ভিডিওটি ভালো লাগলে লাইক ও সাবস্ক্রাইব করতে ভুলবেন না!"
            else:
                text = f"এদিকে গল্পের পরবর্তী ধাপে {main_char}-এর জীবনে এক নতুন মোড় আসে। {plot_sentence} {chunk_info}"
        elif language == "hi":
            if act == "hook":
                text = f"आज की हमारी रोमांचक फिल्म '{title}' की शुरुआत एक बेहद दिलचस्प दृश्य से होती है। {plot_sentence}"
            elif act == "resolution":
                text = f"कहानी के अंत में सारी बुराई का खात्मा होता है और न्याय की जीत होती है। {plot_sentence} अगर आपको यह एक्सप्लेनेशन पसंद आया तो लाइक और सब्सक्राइब जरूर करें!"
            else:
                text = f"कहानी के अगले मोड़ पर {main_char} के सामने एक बड़ी चुनौती आती है। {plot_sentence} {chunk_info}"
        else:
            if act == "hook":
                text = f"The story of '{title}' opens with an atmosphere of high drama and mystery. {plot_sentence}"
            elif act == "resolution":
                text = f"In the dramatic resolution of '{title}', truth and justice finally prevail over darkness. {plot_sentence} Thank you for watching, and remember to like and subscribe for more epic movie breakdowns!"
            else:
                text = f"As the narrative unfolds, {main_char} faces a critical test that shifts the stakes of the story. {plot_sentence} {chunk_info}"

        segments.append({
            "segment_id": idx + 1,
            "act": act,
            "narration_text": text.strip()
        })

    return segments


def _build_bangla_8act_script(
    title: str,
    num_segments: int,
    words_per_segment: int,
    template: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Backward-compatible helper for Bangla beats."""
    from app.ai.movie_beats import BANGLA_SCENE_BEATS
    return _format_beats_into_segments(BANGLA_SCENE_BEATS, num_segments, "bn")


def _build_hindi_8act_script(
    title: str,
    num_segments: int,
    words_per_segment: int,
    template: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Backward-compatible helper for Hindi beats."""
    beats = [
        ("hook", f"कहानी की शुरुआत होती है फिल्म '{title}' के एक दिलचस्प दृश्य से।"),
        ("setup", "किरदार अपनी सामान्य ज़िंदगी में आगे बढ़ रहे होते हैं जब अचानक हालात बदलने लगते हैं।"),
        ("inciting_incident", "एक अप्रत्याशित घटना पूरी कहानी का रुख मोड़ देती है।"),
        ("investigation", "सच्चाई की खोज में किरदार नए रहस्यों और चुनौतियों का सामना करते हैं।"),
        ("escalation", "तनाव और ख़तरा अपने चरम पर पहुँच जाता है।"),
        ("revelations", "एक चौंकाने वाला राज़ सबके सामने आता है।"),
        ("climax", "अंतिम और निर्णायक मुकाबले में सच्चाई और इंसाफ की जीत होती है।"),
        ("resolution", "कहानी एक संतोषजनक मोड़ पर समाप्त होती है। लाइक और सब्सक्राइब जरूर करें!")
    ]
    return _format_beats_into_segments(beats, num_segments, "hi")


def _build_english_8act_script(
    title: str,
    num_segments: int,
    words_per_segment: int,
    template: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Backward-compatible helper for English beats."""
    from app.ai.movie_beats import ENGLISH_SCENE_BEATS
    return _format_beats_into_segments(ENGLISH_SCENE_BEATS, num_segments, "en")

