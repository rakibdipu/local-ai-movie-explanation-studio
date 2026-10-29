"""Localization and language styling adapter for English, Bangla, and Hindi."""

from typing import Dict, Any, List


SCRIPT_TEMPLATES = {
    "en": {
        "hook_intro": "Have you ever wondered what happens when one single choice spirals completely out of control? In today's story, we explore a thrilling journey that will keep you on the edge of your seat.",
        "setup_prefix": "The story begins by introducing our central world.",
        "incident_prefix": "Everything changes when an unexpected event suddenly shatters the calm.",
        "escalation_prefix": "As tensions rise, our characters are pushed to their absolute limits.",
        "climax_prefix": "Now comes the decisive moment that everyone has been waiting for.",
        "resolution_prefix": "In the end, all the pieces fall into place, leaving us with a powerful conclusion.",
        "outro": "What did you think of the ending? Let us know in the comments below, and don't forget to like and subscribe for more complete movie breakdowns!",
        "transition_words": ["Meanwhile,", "Soon after,", "Without warning,", "Little did they know,", "At that exact moment,"]
    },
    "bn": {
        "hook_intro": "আপনি কি কখনো ভেবে দেখেছেন, একটি ছোট্ট সিদ্ধান্ত কীভাবে মানুষের পুরো জীবন বদলে দিতে পারে? আজকের গল্পে আমরা দেখতে পাব এমন এক রোমাঞ্চকর কাহিনী, যা শেষ মুহূর্ত পর্যন্ত আপনাকে আটকে রাখবে।",
        "setup_prefix": "গল্পের শুরুতে আমরা দেখতে পাই আমাদের প্রধান চরিত্রদের পরিচিত পরিবেশ।",
        "incident_prefix": "কিন্তু হঠাৎ করেই ঘটে যায় এক অভাবনীয় ঘটনা, যা সবকিছুকে ওলটপালট করে দেয়।",
        "escalation_prefix": "ঘটনা যত এগোতে থাকে, রহস্য আর বিপদের মাত্রা ততই বাড়তে থাকে।",
        "climax_prefix": "অবশেষে আসে সেই চরম মুহূর্ত, যার জন্য সবাই অপেক্ষা করছিল।",
        "resolution_prefix": "সব জল্পনা-কল্পনার অবসান ঘটিয়ে কাহিনী পৌঁছায় তার চূড়ান্ত পরিণামে।",
        "outro": "এই গল্পের ক্লাইম্যাক্স আপনার কেমন লাগলো? কমেন্ট করে জানান, আর এমন আরও সিনেমা ব্যাখ্যার জন্য আমাদের সাথেই থাকুন!",
        "transition_words": ["ঠিক সেই সময়,", "কিছুক্ষণ পর,", "এদিকে অন্য প্রান্তে,", "কেউ ঘুণাক্ষরেও ভাবতে পারেনি,", "তখনই ঘটে সেই ঘটনা,"]
    },
    "hi": {
        "hook_intro": "क्या आपने कभी सोचा है कि एक छोटा सा फैसला किसी की पूरी जिंदगी कैसे बदल सकता है? आज की इस कहानी में हम एक ऐसा रोमांचक सफर देखेंगे जो आपको अंत तक बांधे रखेगा।",
        "setup_prefix": "कहानी की शुरुआत में हम अपने मुख्य किरदारों और उनकी दुनिया को देखते हैं।",
        "incident_prefix": "लेकिन तभी अचानक एक ऐसी घटना घटती है, जो सब कुछ पूरी तरह बदल देती है।",
        "escalation_prefix": "जैसे-जैसे कहानी आगे बढ़ती है, सस्पेंस और खतरा और भी गहरा होता जाता है।",
        "climax_prefix": "और अब आता है वो निर्णायक मोड़, जिसका सभी को इंतजार था।",
        "resolution_prefix": "आखिरकार सभी रहस्यों से पर्दा उठता है और कहानी अपने अंतिम नतीजे पर पहुंचती है।",
        "outro": "इस कहानी का क्लाइमैक्स आपको कैसा लगा? कमेंट में जरूर बताएं, और ऐसी ही शानदार मूवी एक्सप्लेनेशन के लिए जुड़े रहें!",
        "transition_words": ["ठीक उसी समय,", "कुछ ही देर बाद,", "दूसरी तरफ,", "किसी ने सोचा भी नहीं था,", "तभी अचानक,"]
    }
}


def get_language_template(lang_code: str) -> Dict[str, Any]:
    """Retrieve language specific narrative templates and transition markers."""
    code = lang_code.lower()
    if code in ("bn", "bangla", "bengali"):
        return SCRIPT_TEMPLATES["bn"]
    elif code in ("hi", "hindi"):
        return SCRIPT_TEMPLATES["hi"]
    return SCRIPT_TEMPLATES["en"]
