"""Online story research module fetching real movie synopses, characters, and plot beats.

Queries Wikipedia, TMDb, or public movie databases to provide authentic, detailed
plot points and character names for explanation script generation.
"""

import os
import re
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional
from app.core.logger import get_logger

logger = get_logger()


def clean_search_title(raw_title: str) -> Dict[str, Any]:
    """Clean video filename or title to extract primary movie name, year, and actors.

    Examples:
        "Khalifa (2026) New Released Hindi Dubbed Full Movie ｜ Starring Prithviraj, Neil [IFdcpzZrT80]"
        -> {"title": "Khalifa", "year": "2026", "keywords": "Khalifa 2026 Prithviraj"}
    """
    clean = raw_title

    # Remove file extensions
    clean = re.sub(r"\.(mp4|mkv|webm|avi|mov)$", "", clean, flags=re.I)

    # Remove YouTube ID in brackets like [IFdcpzZrT80]
    clean = re.sub(r"\[[\w-]+\]", "", clean)

    # Extract year if present (19xx or 20xx)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", clean)
    year = year_match.group(1) if year_match else None

    # Remove common YouTube junk words
    junk_patterns = [
        r"new released", r"hindi dubbed", r"full movie", r"south indian movie",
        r"blockbuster", r"action thriller", r"hd\b", r"4k\b", r"1080p\b",
        r"starring\s+[^\n\|]+", r"dir(?:ected by)?\s+[^\n\|]+",
    ]
    for jp in junk_patterns:
        clean = re.sub(jp, "", clean, flags=re.I)

    # Split on pipe, dash, colon, or parentheses (including full-width pipe \uff5c)
    parts = re.split(r"[\|\-–—\uff5c]", clean)
    main_name = parts[0].strip()

    # Clean out parentheses around years
    main_name = re.sub(r"\(.*?\)", "", main_name).strip()
    # Normalize multiple whitespace
    main_name = re.sub(r"\s+", " ", main_name).strip()

    search_query = main_name
    if year:
        search_query += f" {year} film"
    else:
        search_query += " film"

    return {
        "title": main_name,
        "year": year,
        "search_query": search_query.strip(),
        "raw_title": raw_title
    }


def fetch_wikipedia_movie_data(search_query: str) -> Optional[Dict[str, Any]]:
    """Search Wikipedia for movie article and extract plot and cast information."""
    logger.info(f"Searching Wikipedia for movie details: '{search_query}'...")
    
    # 1. Search for page
    search_url = (
        f"https://en.wikipedia.org/w/api.php?action=query&list=search&"
        f"srsearch={urllib.parse.quote(search_query)}&format=json"
    )
    headers = {"User-Agent": "MovieExplanationStudio/2.0 (Local Research)"}
    
    try:
        req = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            search_results = data.get("query", {}).get("search", [])
            if not search_results:
                return None
            top_hit = search_results[0]
            page_title = top_hit.get("title")
    except Exception as exc:
        logger.warning(f"Wikipedia search failed: {exc}")
        return None

    logger.info(f"Found Wikipedia article: '{page_title}'")

    # 2. Get sections of the article
    sections_url = (
        f"https://en.wikipedia.org/w/api.php?action=parse&page={urllib.parse.quote(page_title)}&"
        f"prop=sections&format=json"
    )
    plot_section_idx = None
    cast_section_idx = None

    try:
        req = urllib.request.Request(sections_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sections = data.get("parse", {}).get("sections", [])
            for s in sections:
                line_lower = s.get("line", "").lower()
                if "plot" in line_lower or "synopsis" in line_lower or "premise" in line_lower:
                    if plot_section_idx is None:
                        plot_section_idx = s.get("index")
                elif "cast" in line_lower:
                    if cast_section_idx is None:
                        cast_section_idx = s.get("index")
    except Exception as exc:
        logger.warning(f"Failed to fetch Wikipedia sections: {exc}")

    # 3. Fetch Plot Section Text
    plot_text = ""
    if plot_section_idx is not None:
        text_url = (
            f"https://en.wikipedia.org/w/api.php?action=parse&page={urllib.parse.quote(page_title)}&"
            f"section={plot_section_idx}&prop=wikitext&format=json"
        )
        try:
            req = urllib.request.Request(text_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_wiki = data.get("parse", {}).get("wikitext", {}).get("*", "")
                plot_text = _clean_wikitext(raw_wiki)
        except Exception as exc:
            logger.warning(f"Failed to fetch Wikipedia plot: {exc}")

    # 4. Fetch Cast Section Text
    cast_text = ""
    cast_characters = []
    if cast_section_idx is not None:
        cast_url = (
            f"https://en.wikipedia.org/w/api.php?action=parse&page={urllib.parse.quote(page_title)}&"
            f"section={cast_section_idx}&prop=wikitext&format=json"
        )
        try:
            req = urllib.request.Request(cast_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_wiki = data.get("parse", {}).get("wikitext", {}).get("*", "")
                cast_text = _clean_wikitext(raw_wiki)
                cast_characters = _extract_characters_from_cast(raw_wiki)
        except Exception as exc:
            logger.warning(f"Failed to fetch Wikipedia cast: {exc}")

    # If no plot section was found, fetch summary lead paragraph
    if not plot_text:
        lead_url = (
            f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=true&"
            f"titles={urllib.parse.quote(page_title)}&explaintext=true&format=json"
        )
        try:
            req = urllib.request.Request(lead_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                pages = data.get("query", {}).get("pages", {})
                for p in pages.values():
                    plot_text = p.get("extract", "")
                    break
        except Exception:
            pass

    if not plot_text and not cast_characters:
        return None

    return {
        "article_title": page_title,
        "plot": plot_text.strip(),
        "cast_text": cast_text.strip(),
        "characters": cast_characters,
        "source": "Wikipedia"
    }


def _clean_wikitext(text: str) -> str:
    """Strip Wikipedia markup, templates, citations, and brackets."""
    # Remove section header
    text = re.sub(r"^==+.*?==+", "", text, flags=re.MULTILINE)
    # Remove templates {{...}}
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    # Remove citations <ref>...</ref> or <ref.../>
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    text = re.sub(r"<ref[^>]*/>", "", text)
    # Convert links [[Target|Label]] -> Label, [[Target]] -> Target
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    # Remove bold / italic markup
    text = re.sub(r"'''+|''+", "", text)
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Normalize whitespace
    text = re.sub(r"\n{2,}", "\n\n", text).strip()
    return text


def _extract_characters_from_cast(raw_wiki: str) -> List[Dict[str, str]]:
    """Extract list of {actor, character, role} from wikitext cast listing."""
    characters = []
    lines = raw_wiki.split("\n")
    for line in lines:
        line = line.strip()
        if not line.startswith("*"):
            continue
        cleaned = _clean_wikitext(line.lstrip("*").strip())
        if not cleaned:
            continue
        # Patterns like: "Actor as Character: description"
        match = re.search(r"^(.*?)\s+as\s+(.*?)(?::\s*(.*))?$", cleaned, flags=re.IGNORECASE)
        if match:
            actor = match.group(1).strip()
            char = match.group(2).strip()
            desc = match.group(3).strip() if match.group(3) else ""
            characters.append({"actor": actor, "character": char, "description": desc})
        elif ":" in cleaned:
            parts = cleaned.split(":", 1)
            characters.append({"actor": parts[0].strip(), "character": parts[1].strip(), "description": ""})
    return characters


def research_movie(raw_title: str) -> Dict[str, Any]:
    """Execute complete online story research pipeline for a movie.

    Returns structured dict with:
        title, year, plot, characters, lead_protagonist, lead_antagonist,
        story_beats, verified=True/False
    """
    cleaned = clean_search_title(raw_title)
    wiki_data = fetch_wikipedia_movie_data(cleaned["search_query"])

    if not wiki_data and cleaned.get("year"):
        # Try without year
        wiki_data = fetch_wikipedia_movie_data(f"{cleaned['title']} film")

    if not wiki_data:
        # Fallback: check if major actor names appear in raw title (e.g. Jackie Chan & Arnold Schwarzenegger)
        actors = re.findall(r"\b(Jackie Chan|Arnold Schwarzenegger|Prithviraj|Shah Rukh Khan|Salman Khan|Tom Cruise)\b", raw_title, flags=re.I)
        if len(actors) >= 2:
            actor_query = f"{' '.join(actors)} film"
            logger.info(f"Attempting actor-based Wikipedia search: '{actor_query}'...")
            wiki_data = fetch_wikipedia_movie_data(actor_query)

    if not wiki_data:
        logger.info(f"No online encyclopedia match for '{cleaned['title']}'. Using heuristic fallback.")
        return {
            "title": cleaned["title"],
            "year": cleaned.get("year"),
            "plot": "",
            "characters": [],
            "lead_protagonist": "Protagonist",
            "lead_antagonist": "Antagonist",
            "verified": False,
            "source": "heuristic"
        }

    chars = wiki_data.get("characters", [])
    lead_protagonist = chars[0].get("character") if chars else "Protagonist"
    lead_antagonist = chars[1].get("character") if len(chars) > 1 else "Antagonist"

    result = {
        "title": cleaned["title"],
        "year": cleaned.get("year"),
        "article_title": wiki_data.get("article_title"),
        "plot": wiki_data.get("plot", ""),
        "characters": chars,
        "lead_protagonist": lead_protagonist,
        "lead_antagonist": lead_antagonist,
        "verified": True,
        "source": wiki_data.get("source", "Wikipedia")
    }

    logger.info(
        f"Online research successful for '{result['title']}': "
        f"{len(result['characters'])} characters identified, {len(result['plot'].split())} words of plot summary."
    )
    return result
