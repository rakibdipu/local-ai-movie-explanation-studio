"""High-impact YouTube thumbnail generator with multilingual text composition."""

import os
import glob
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from app.ai.visual_analyzer import extract_frame_at_timestamp
from app.core.logger import get_logger
from app.utils.files import safe_write_json

logger = get_logger()

# System font discovery paths
FONT_CANDIDATES = {
    "bn": [
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansBengaliUI-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerifBengali-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ],
    "hi": [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-SemiBold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerifDevanagari-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ],
    "en": [
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
}


def find_best_font(language: str, size: int = 48) -> ImageFont.FreeTypeFont:
    """Find and load the best available TTF font for the selected language."""
    lang_code = language.lower()
    candidates = FONT_CANDIDATES.get(lang_code, FONT_CANDIDATES["en"]) + FONT_CANDIDATES["en"]
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def generate_thumbnail_concepts(master_story: Dict[str, Any], language: str = "en") -> List[Dict[str, str]]:
    """Generate 3 curiosity-driven, truthful thumbnail concepts based on the story."""
    lang_code = language.lower()
    logline = master_story.get("logline", "")

    if lang_code == "bn":
        return [
            {
                "id": "concept_1",
                "headline": "একটি রহস্য... যার শেষটা কেউ ভাবেনি!",
                "badge": "সম্পূর্ণ ব্যাখ্যা",
                "angle": "Mystery & shock reveal"
            },
            {
                "id": "concept_2",
                "headline": "এই সিদ্ধান্ত পুরো গল্প বদলে দিল!",
                "badge": "ফুল মুভি রিক্যাপ",
                "angle": "Turning point decision"
            },
            {
                "id": "concept_3",
                "headline": "শেষ মুহূর্তের অবিশ্বাস্য ক্লাইম্যাক্স!",
                "badge": "সিনেমা রহস্য",
                "angle": "Climactic twist"
            }
        ]
    elif lang_code == "hi":
        return [
            {
                "id": "concept_1",
                "headline": "एक ऐसा राज़... जो किसी ने नहीं सोचा था!",
                "badge": "पूरी कहानी",
                "angle": "Mystery & shock reveal"
            },
            {
                "id": "concept_2",
                "headline": "इस फैसले ने सब कुछ बदल दिया!",
                "badge": "फुल मूवी रीकैप",
                "angle": "Turning point decision"
            },
            {
                "id": "concept_3",
                "headline": "अंतिम मोड़ जिसने सबको चौंका दिया!",
                "badge": "सिनेमा सस्पेंस",
                "angle": "Climactic twist"
            }
        ]
    else:
        return [
            {
                "id": "concept_1",
                "headline": "THE TRUTH NOBODY EXPECTED!",
                "badge": "FULL EXPLANATION",
                "angle": "Shocking reveal"
            },
            {
                "id": "concept_2",
                "headline": "ONE CHOICE CHANGED EVERYTHING!",
                "badge": "MOVIE BREAKDOWN",
                "angle": "Pivotal turn"
            },
            {
                "id": "concept_3",
                "headline": "THE CLIMAX NOBODY SAW COMING!",
                "badge": "STORY EXPLAINED",
                "angle": "Twist ending"
            }
        ]


def create_thumbnail(
    movie_path: str,
    master_story: Dict[str, Any],
    scenes: List[Dict[str, Any]],
    output_dir: str,
    language: str = "en",
    width: int = 1280,
    height: int = 720
) -> str:
    """Compose and save a high-contrast YouTube thumbnail with text overlay and gradient."""
    os.makedirs(output_dir, exist_ok=True)
    lang_code = language.lower()

    # 1. Generate Concepts
    concepts = generate_thumbnail_concepts(master_story, lang_code)
    chosen_concept = concepts[0]  # Strongest primary concept
    safe_write_json(os.path.join(output_dir, "concepts.json"), concepts)

    # 2. Pick a high-dramatic frame (around 65-75% of movie duration for climax/twist)
    best_frame_sec = 60.0
    if scenes:
        climax_scene_idx = min(len(scenes) - 1, int(len(scenes) * 0.70))
        best_frame_sec = scenes[climax_scene_idx]["keyframe_seconds"]

    temp_raw_frame = os.path.join(output_dir, "raw_frame.jpg")
    extract_frame_at_timestamp(movie_path, best_frame_sec, temp_raw_frame, width, height)

    if os.path.isfile(temp_raw_frame):
        base_img = Image.open(temp_raw_frame).convert("RGB")
    else:
        # Fallback dark background
        base_img = Image.new("RGB", (width, height), color=(20, 20, 30))

    # Enhance visual contrast and saturation for YouTube punch
    enhancer_con = ImageEnhance.Contrast(base_img)
    base_img = enhancer_con.enhance(1.25)
    enhancer_col = ImageEnhance.Color(base_img)
    base_img = enhancer_col.enhance(1.20)

    # 3. Apply dark vignette & bottom gradient for text contrast
    gradient = Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
    draw_grad = ImageDraw.Draw(gradient)

    # Dark bottom third
    for y in range(int(height * 0.45), height):
        alpha = int(((y - height * 0.45) / (height * 0.55)) * 210)
        draw_grad.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    # Dark top left for badge
    for y in range(0, int(height * 0.25)):
        alpha = int((1.0 - (y / (height * 0.25))) * 140)
        draw_grad.line([(0, y), (int(width * 0.5), y)], fill=(0, 0, 0, alpha))

    base_img = Image.alpha_composite(base_img.convert("RGBA"), gradient).convert("RGB")
    draw = ImageDraw.Draw(base_img)

    # 4. Render Badge
    badge_text = chosen_concept["badge"]
    font_badge = find_best_font(lang_code, size=26)
    badge_x, badge_y = 50, 45
    draw.rectangle([badge_x - 10, badge_y - 6, badge_x + 240, badge_y + 36], fill=(220, 20, 60))
    draw.text((badge_x, badge_y), badge_text, font=font_badge, fill=(255, 255, 255))

    # 5. Render Main Headline with stroke/outline
    headline = chosen_concept["headline"]
    font_title = find_best_font(lang_code, size=52)

    text_x = 50
    text_y = height - 140

    # Draw bold outline for ultra high readability
    outline_color = (0, 0, 0)
    for ox in range(-4, 5):
        for oy in range(-4, 5):
            draw.text((text_x + ox, text_y + oy), headline, font=font_title, fill=outline_color)

    # Main text in vibrant yellow / white
    draw.text((text_x, text_y), headline, font=font_title, fill=(255, 225, 0))

    final_thumb_path = os.path.join(output_dir, "final_thumbnail.png")
    base_img.save(final_thumb_path, "PNG")
    logger.info(f"Thumbnail created successfully -> {final_thumb_path}")

    return final_thumb_path
