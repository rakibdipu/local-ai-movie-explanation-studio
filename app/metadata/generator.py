"""YouTube title, description, chapters, and metadata generation."""

import os
from typing import Dict, Any, List
from app.core.logger import get_logger
from app.utils.files import safe_write_json
from app.utils.timecode import seconds_to_hms

logger = get_logger()


def generate_metadata(
    movie_filename: str,
    master_story: Dict[str, Any],
    timeline_data: Dict[str, Any],
    language: str,
    duration_target_minutes: int,
    narration_style: str,
    output_dir: str
) -> Dict[str, Any]:
    """Generate YouTube-ready titles, description, timestamps/chapters, hashtags, and disclaimer."""
    os.makedirs(output_dir, exist_ok=True)
    lang_code = language.lower()

    # Generate 5 title candidates
    title_options = _generate_titles(movie_filename, master_story, lang_code)

    # Generate chapters / timestamps from timeline items
    chapters = []
    items = timeline_data.get("items", [])
    for it in items:
        start_sec = it.get("timeline_start_seconds", 0.0)
        act_name = it.get("act", "Story Scene").replace("_", " ").title()
        time_str = seconds_to_hms(start_sec)
        chapters.append(f"{time_str} - {act_name}")

    chapters_text = "\n".join(chapters) if chapters else "00:00:00 - Story Begins"

    # Description template
    description = _generate_description(
        movie_filename=movie_filename,
        story=master_story,
        chapters_text=chapters_text,
        language=lang_code
    )

    hashtags = _generate_hashtags(lang_code)

    metadata = {
        "language": lang_code,
        "duration_target": f"{duration_target_minutes}m",
        "style": narration_style,
        "title_options": title_options,
        "primary_title": title_options[0],
        "description": description,
        "hashtags": hashtags,
        "thumbnail_text": title_options[0],
        "disclaimer": (
            "IMPORTANT: This video provides transformative commentary, educational breakdown, "
            "and narrative explanation. Review the final video and verify your rights before publication."
        )
    }

    out_file = os.path.join(output_dir, "metadata.json")
    safe_write_json(out_file, metadata)
    logger.info(f"Metadata generated and saved to {out_file}")

    return metadata


def _generate_titles(movie_name: str, story: Dict[str, Any], language: str) -> List[str]:
    """Generate 5 curiosity-driven titles in the target language."""
    base_name = os.path.splitext(movie_name)[0].replace("_", " ").title()

    if language == "bn":
        return [
            f"একটি অদ্ভুত সিদ্ধান্ত যা পুরো শহরকে বদলে দিল | {base_name} সম্পূর্ণ গল্প ব্যাখ্যা",
            f"রহস্যময় এক অপরাধ... যার শেষ পরিণতি কেউ ভাবেনি! | {base_name} মুভি রিক্যাপ",
            f"এই সত্য প্রকাশ পাওয়ার পর সবকিছু বদলে গেল | বাংলা সিনেমা ব্যাখ্যা",
            f"{base_name} সিনেমার অবিশ্বাস্য সমাপ্তি ও সম্পূর্ণ কাহিনী বিশ্লেষণ",
            f"টানটান উত্তেজনায় ঘেরা এক গল্প! {base_name} Full Story Breakdown in Bangla"
        ]
    elif language == "hi":
        return [
            f"एक ऐसा फैसला जिसने सब कुछ बदल दिया | {base_name} Full Movie Explanation in Hindi",
            f"एक रहस्यमयी घटना... जिसका अंजाम किसी ने नहीं सोचा था! | {base_name} Recap",
            f"जब असली सच सामने आया तो होश उड़ गए | हिंदी मूवी एक्सप्लेनेशन",
            f"{base_name} का हैरान कर देने वाला क्लाइमैक्स और पूरी कहानी",
            f"सस्पेंस और थ्रिल से भरी कहानी | {base_name} Complete Story Breakdown"
        ]
    else:
        return [
            f"The One Choice That Spiraled Out Of Control | {base_name} Full Movie Explained",
            f"A Mystery Nobody Could Solve Until It Was Too Late | {base_name} Recap",
            f"The Shocking Truth Revealed! | {base_name} Ending & Complete Story Breakdown",
            f"Why This Twist Changed Everything | {base_name} Explained In-Depth",
            f"The Most Intense Climax Explained | {base_name} Film Recap"
        ]


def _generate_description(movie_filename: str, story: Dict[str, Any], chapters_text: str, language: str) -> str:
    """Generate comprehensive YouTube description with spoiler warnings and rights disclaimer."""
    logline = story.get("logline", "An incredible cinematic story breakdown.")

    if language == "bn":
        return f"""🎬 সম্পূর্ণ সিনেমা ব্যাখ্যা এবং গল্প বিশ্লেষণ:

{logline}

আজকের ভিডিওতে আমরা এই টানটান রোমাঞ্চকর সিনেমাটির প্রতিটি গুরুত্বপূর্ণ দৃশ্য, রহস্য এবং ক্লাইম্যাক্স বিস্তারিত আলোচনা করেছি।

⏱️ টাইমস্ট্যাম্প / অধ্যায়:
{chapters_text}

⚠️ সতর্কতা: এই ভিডিওটিতে সম্পূর্ণ সিনেমার স্পয়লার অন্তর্ভুক্ত রয়েছে।

⚖️ কপিরাইট ও নীতিমালা সংক্রান্ত তথ্য:
এই ভিডিওটি একটি রূপান্তরমূলক পর্যালোচনা এবং শিক্ষামূলক সিনেমা ব্যাখ্যা (Transformative Commentary & Film Analysis)। মূল চলচ্চিত্রের সমস্ত স্বত্বাধিকার সংশ্লিষ্ট প্রযোজক ও স্বত্বাধিকারীদের সংরক্ষিত। প্রকাশনার পূর্বে দয়া করে প্রয়োজনীয় স্বত্বাধিকার যাচাই করুন।

#MovieExplainer #BanglaMovieRecap #সিনেমা_ব্যাখ্যা
"""
    elif language == "hi":
        return f"""🎬 पूरी फिल्म की कहानी और क्लाइमैक्स एक्सप्लेनेशन:

{logline}

आज के इस वीडियो में हम इस रोमांचक कहानी के हर अहम मोड़, रहस्यों और अंतिम नतीजे को विस्तार से समझेंगे।

⏱️ टाइमस्टैम्प / चैप्टर्स:
{chapters_text}

⚠️ स्पॉइलर अलर्ट: इस वीडियो में फिल्म की पूरी कहानी का विवरण है।

⚖️ डिस्क्लेमर:
यह वीडियो एक व्याख्यात्मक, शैक्षिक और समीक्षात्मक प्रस्तुति है। मूल फिल्म के सभी कॉपीराइट उनके संबंधित स्वामियों के पास सुरक्षित हैं।

#MovieExplainer #HindiMovieExplanation #मूवी_एक्सप्लेनेशन
"""
    else:
        return f"""🎬 Complete Movie Explanation & Story Breakdown:

{logline}

In today's video, we break down every crucial plot development, hidden clue, character motive, and the unforgettable ending.

⏱️ Timestamps & Chapters:
{chapters_text}

⚠️ Spoiler Notice: This video contains full plot explanations and spoilers.

⚖️ Rights & Fair Use Disclaimer:
This video is a transformative narrative breakdown and commentary for educational and analytical purposes. All rights to the underlying movie belong to their respective copyright holders. Review your licensing and permissions before public distribution.

#MovieExplanation #Recap #FilmBreakdown #StoryExplained
"""


def _generate_hashtags(language: str) -> List[str]:
    if language == "bn":
        return ["#MovieExplanation", "#BanglaRecap", "#সিনেমা_ব্যাখ্যা", "#MovieBreakdown"]
    elif language == "hi":
        return ["#MovieExplanation", "#HindiRecap", "#मूवी_एक्सप्लेनेशन", "#FilmExplained"]
    return ["#MovieExplanation", "#MovieRecap", "#EndingExplained", "#FilmBreakdown"]
