"""
QueryBuilder — lambe sawaal ka ASLI topic nikaalna (Spec Section 1 + 2 ka base)

KYUN YE FILE BANI (live test, energy question, 2026-08-19):
    User ne ek 2000-character ka instruction-style sawaal diya:

        "मान लो मानव सभ्यता को अगले 100 वर्षों में एक ऐसी ऊर्जा तकनीक खोजनी है ...
         Physics, materials science ... research papers, books, PDFs ... खोजो ...
         कम-से-कम 3 hypotheses बनाओ ... HYPOTHESIS label करो ..."

    Wapas jo sources aaye wo the: Gagea (ek phool) ki botanical research, CPEC
    ki cultural implications, WHO surgeons density, WHO foodborne deaths. Yaani
    energy se ZERO lena-dena.

    Wajah koi API nahi thi — hamari khud ki query thi. Purana raasta:
        clean_query() -> poora 2000-char prompt (Devanagari filler bhi andar)
        connectors/base.content_terms(query, limit=6) -> query ke PEHLE 6 terms

    Pehle 6 terms the: "मान", "मानव", "सभ्यता", "अगले", "वर्षों", "ऐसी" —
    matlab search "human civilization next years" par chali, "energy technology"
    par nahi. Aur poori 2000-char string URL mein bhejne se OpenAlex ne HTTP 400
    diya (query too long). Do galtiyan ek saath.

ISKA ILAAJ (poora rule-based, ek bhi Gemini call nahi):
    1. Instruction-style prompt pehchaano (lamba + "batao/khojo/research karo"
       jaisa meta vocabulary).
    2. Filler + INSTRUCTION shabd hataao ("research", "sources", "hypothesis",
       "बताओ", "खोजो", "कम-से-कम") — ye batate hain ki KAISE kaam karna hai,
       topic nahi batate.
    3. Bache shabdon ko score do: kitni baar aaye (topic dohraya jaata hai) +
       pehle vaakya mein aaye ya nahi (topic aksar shuru mein hota hai).
    4. Devanagari term ko English mein badlo (ऊर्जा -> energy), kyunki papers,
       datasets aur books ka index English mein hai. Hindi mein search karke
       "0 result" aana research engine ki kami hai, duniya ki nahi.
    5. Query ki lambai par hard cap — koi API ko 2000-char query nahi jaati.

ZAROORI: ye SIRF andar ke search ke liye hai. User ka sawaal jaisa hai waisa hi
prompt mein jaata hai, aur uski bhasha/spelling par kabhi comment nahi hota.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from .local_language import normalize

# ── tokenizer (Devanagari-safe) ──────────────────────────────────────────────
# Matra/nukta/virama Unicode mein "combining mark" (Mn/Mc) hain aur Python ka
# \w unhe word-character nahi maanta — isliye "मधुमेह" tootkar ["मध","म","ह"]
# ban jaata tha. Ranges hand-type karne ke bajaye unicodedata se banate hain
# taaki Bangla/Gurmukhi/Tamil par bhi apne aap sahi rahe.
_MARKS = "".join(
    chr(cp) for cp in range(0x0300, 0x0E00)
    if unicodedata.category(chr(cp)) in ("Mn", "Mc")
)
_WORD_CHAR = r"[^\W_]"
_TERM_CHAR = f"(?:{_WORD_CHAR}|[{re.escape(_MARKS)}])"
_TERM_RE = re.compile(
    f"{_WORD_CHAR}{_TERM_CHAR}*(?:[-'/]{_WORD_CHAR}{_TERM_CHAR}*)*", re.UNICODE)
# Sirf Roman/angrezi shabd (a-z, hyphen, apostrophe). Devanagari ya koi bhi
# non-Latin token search query mein nahi jaana chahiye — papers ka index English
# mein hai, aur Hindi token bhejne par 0 result aata hai.
_ROMAN_ONLY = re.compile(r"^[a-z][a-z\-'/]*$")

# ── function words (Roman + Devanagari) ─────────────────────────────────────
_STOP = {
    "the", "a", "an", "of", "and", "or", "in", "on", "for", "to", "with", "is",
    "are", "was", "were", "be", "been", "by", "from", "at", "as", "that", "this",
    "these", "those", "it", "its", "if", "so", "than", "then", "there", "here",
    "not", "no", "but", "can", "could", "should", "would", "may", "might", "will",
    "shall", "do", "does", "did", "has", "have", "had", "any", "all", "some",
    "such", "very", "more", "most", "less", "least", "much", "many", "into",
    "about", "between", "among", "over", "under", "after", "before", "while",
    "where", "when", "which", "what", "who", "whom", "whose", "how", "why",
    # Hinglish (roman)
    "kya", "hai", "hain", "tha", "thi", "the", "ka", "ki", "ke", "ko", "se",
    "mein", "me", "par", "aur", "ya", "bhi", "hi", "to", "jo", "wo", "ye",
    "yah", "vah", "is", "us", "isi", "usi", "koi", "kuch", "sab", "sabhi",
    "abhi", "phir", "lekin", "agar", "jaise", "jaisa", "tarah", "wale", "wala",
    "hota", "hoti", "hote", "hona", "kar", "karna", "karne", "kiya", "raha",
    "rahi", "rahe", "gaya", "gayi", "liye", "apne", "apna", "mera", "meri",
    "tum", "tumhe", "aap", "aapko", "mujhe", "main", "hum", "unka", "uska",
    # Hinglish — ye bache hue function shabd search query mein chale jaate the
    # ("cancer nai drug", "black holes bare"), isliye yahan bhi hone chahiye
    "kaise", "kaisa", "kaisi", "kese", "kesa", "karte", "karti", "karta",
    "karen", "kare", "kiye", "bare", "baare", "sath", "saath", "baad",
    "pehle", "phle", "nai", "nayi", "naya", "naye", "zyada", "jyada",
    "adhik", "thoda", "thodi", "bilkul", "sirf", "keval", "yaani", "matlab",
    "mtlb", "waise", "aisa", "aise", "aisi", "kab", "kahan", "kyun", "kyu",
    "warna", "isliye", "kitna", "kitni", "kitne", "bahut", "bht", "acha",
    "accha", "theek", "thik", "chahiye", "hoga", "hogi", "honge", "diya",
    "dena", "lena", "sakta", "sakti", "sakte", "bina", "andar", "bahar",
    "hua", "hui", "hue", "huye", "karu", "karun", "kru", "kam", "kum",
    "chahta", "chahti", "chahte", "wala", "waali", "wali", "nahin", "nhi",
    # Devanagari function words
    "क्या", "है", "हैं", "था", "थी", "थे", "का", "के", "की", "को", "में", "पर",
    "से", "और", "या", "यह", "वह", "ये", "वे", "इस", "उस", "जो", "तो", "ही",
    "भी", "कि", "नहीं", "ने", "एक", "लिए", "कैसे", "क्यों", "कौन", "कब",
    "कहाँ", "कहां", "होता", "होती", "होते", "हो", "हों", "होना", "करना",
    "करने", "करो", "किया", "किए", "अपने", "अपना", "बारे", "जैसे", "जैसी",
    "ऐसी", "ऐसा", "ऐसे", "कोई", "कुछ", "सब", "सभी", "अभी", "फिर", "लेकिन",
    "अगर", "मान", "लो", "अगले", "साथ", "बाद", "पहले", "वहाँ", "वहां", "यहाँ",
    "यहां", "उन", "इन", "उनके", "इनके", "तक", "बहुत", "अधिक", "कम", "गुना",
    "आज", "कल", "जहाँ", "जहां", "वाले", "वाला", "रहा", "रही", "रहे", "गया",
    "गयी", "गई", "दे", "देना", "ले", "लेना", "सके", "सकता", "सकती", "सकते",
    "चाहिए", "पड़", "पड़ती", "पड़ता", "मत", "केवल", "सिर्फ", "साफ", "स्पष्ट",
    "प्रत्येक", "हर", "अलग", "आपस", "आपसी", "जरूरी", "जरूर", "बिल्कुल",
    "तुम", "तुम्हें", "तुमको", "तुम्हारा", "तुम्हारे", "हमें", "मुझे", "आपको",
    "आपके", "लगभग", "बल्कि", "यानी", "मतलब", "वगैरह", "आदि", "इसके", "उसके",
    "इसका", "उसका", "इसे", "उसे", "इसी", "उसी", "चूंकि", "क्योंकि", "ताकि",
    "जिससे", "जिसमें", "जिन", "जिनका", "वाली", "वालों", "ओर", "तरफ", "बिना",
}

# ── INSTRUCTION vocabulary ───────────────────────────────────────────────────
# Ye shabd batate hain ki AI ko KAISE kaam karna hai — topic nahi batate.
# Lambe prompt mein ye sabse zyada baar aate hain ("research", "sources",
# "hypothesis", "evidence"), isliye inhe hataye bina frequency-scoring ulta
# nateeja deti hai.
#
# JAAN-BOOJH KAR: ye filter SIRF instruction-style (lambe) prompt par lagta hai.
# "hypothesis testing kaise karte hain" jaisa CHHOTA sawaal aaya to hum
# "hypothesis" ko topic hi maanenge — dekho is_instruction_prompt().
_META = {
    # angrezi — research process ka vocabulary
    "research", "researches", "researching", "study", "studies", "deep",
    "analysis", "analyse", "analyze", "explain", "explanation", "describe",
    "tell", "give", "provide", "list", "listing", "find", "search", "look",
    "read", "reading", "write", "label", "mark", "marked", "clearly",
    "hypothesis", "hypotheses", "hypothesize", "assumption", "assumptions",
    "assume", "evidence", "source", "sources", "paper", "papers", "book",
    "books", "pdf", "pdfs", "patent", "patents", "dataset", "datasets",
    "report", "reports", "internet", "online", "available", "availability",
    "relevant", "relevance", "existing", "field", "fields", "discipline",
    "disciplines", "interdisciplinary", "cross-disciplinary", "knowledge",
    "summary", "summarise", "summarize", "conclusion", "conclusions",
    "unknown", "untested", "speculative", "speculation", "verified",
    "unverified", "fact", "facts", "factual", "inference", "inferences",
    "direction", "directions", "experiment", "experiments", "simulation",
    "simulations", "test", "testing", "tested", "compare", "comparison",
    "competing", "explanations", "support", "supports", "supported",
    "against", "reject", "rejected", "insufficient", "sufficient",
    "important", "answer", "answers", "question", "questions", "topic",
    "according", "please", "step", "steps", "point", "points", "detail",
    "details", "example", "examples", "context", "note", "notes",
    "reliable", "trustworthy", "credible", "peer-reviewed", "full", "text",
    "content", "information", "info", "data",
    # Hinglish (roman) instruction shabd
    "batao", "bataiye", "batana", "bta", "btao", "khojo", "khoj", "dhundo",
    "jodo", "banao", "bnao", "samjhao", "smjhao", "likho", "socho", "karo",
    "kro", "dena", "bolo", "poocho", "jawab", "sawal", "sawaal", "prashn",
    "vishay", "kshetra", "gyaan", "shodh", "anusandhan", "sabut", "saboot",
    "praman", "nishkarsh", "saransh", "udaharan", "tulna",
    # Devanagari instruction shabd
    "बताओ", "बताइए", "बताना", "बताएं", "खोजो", "खोजना", "खोजनी", "ढूंढो",
    "जोड़ो", "जोड़कर", "जोड़ना", "बनाओ", "बनाना", "समझाओ", "लिखो", "दो",
    "सोचो", "पढ़ो", "पढ़ना", "शोध", "अनुसंधान", "अध्ययन", "पेपर", "पेपर्स",
    "किताब", "किताबें", "पुस्तक", "पुस्तकें", "स्रोत", "स्रोतों", "इंटरनेट",
    "डेटासेट", "रिपोर्ट", "रिपोर्ट्स", "जानकारी", "सबूत", "प्रमाण",
    "परिकल्पना", "परिकल्पनाएं", "निष्कर्ष", "उत्तर", "जवाब", "सवाल",
    "प्रश्न", "विषय", "क्षेत्र", "क्षेत्रों", "ज्ञान", "सारांश", "तुलना",
    "उदाहरण", "प्रयोग", "परीक्षण", "साक्ष्य", "समर्थन", "खिलाफ", "विरुद्ध",
    "मान्यता", "मान्यताएं", "धारणा", "निकल", "निकाल", "उपलब्ध", "संबंधित",
    "प्रासंगिक", "सूची", "महत्वपूर्ण", "जानबूझकर", "अंत", "अंततः", "सफल",
    "संभावित", "सुझाव", "प्रस्तुत", "पूरा", "पूरी", "पूर्ण", "मौजूदा",
    "विश्वसनीय", "सामग्री",   # "सामग्री" = content/material — dono, isliye meta
}

# ── HAMESHA filler (chhote sawaal mein bhi) ──────────────────────────────────
# _META poora sirf lambe instruction-prompt par hatta hai, aur ye theek hai:
# "hypothesis testing kaise karte hain" mein "hypothesis" ASLI topic hai.
#
# Par kuch shabd kisi bhi sawaal mein topic nahi hote — "research kya kehti
# hai", "sources batao", "jawab do". Ye do jagah nuksaan karte the:
#   1. Search query mein chale jaate the ("... diabetes asar daalta research
#      kehti") — PubMed/OpenAlex ko Hinglish grammar bhejna faltu hai.
#   2. ZYADA KHATARNAK: relevance guard mein ye "universal match" ban jaate
#      hain. Duniya ka har paper apne abstract mein "research"/"study" likhta
#      hai, to Gagea (phool) ki botany bhi energy ke sawaal par ek hit maar
#      leti thi aur off-topic hone se bach jaati thi.
_ALWAYS_META = {
    # angrezi — har academic text mein maujood, isliye topic ka signal nahi
    "research", "researches", "researching", "study", "studies",
    "paper", "papers", "source", "sources", "evidence", "report", "reports",
    "internet", "online", "available", "availability", "relevant", "relevance",
    "answer", "answers", "question", "questions", "topic", "summary",
    "conclusion", "conclusions", "detail", "details", "example", "examples",
    "please", "according",
    # Hinglish (roman)
    "batao", "bataiye", "batana", "bta", "btao", "khojo", "khoj", "dhundo",
    "samjhao", "smjhao", "smjao", "likho", "socho", "bolo", "poocho", "pucho",
    "jawab", "jvab", "sawal", "sawaal", "prashn", "shodh", "anusandhan",
    "sabut", "saboot", "praman", "nishkarsh", "saransh",
    "kehti", "kehta", "kehte", "kahti", "kahta", "kahte", "kaha",
    "daalta", "daalti", "dalta", "dalti", "padta", "padti", "padte",
    "batati", "batata", "batate",
    # Devanagari
    "बताओ", "बताइए", "बताना", "बताएं", "खोजो", "ढूंढो", "समझाओ", "लिखो",
    "सोचो", "पढ़ो", "शोध", "अनुसंधान", "स्रोत", "स्रोतों", "सबूत", "प्रमाण",
    "जवाब", "उत्तर", "सवाल", "प्रश्न", "सारांश", "निष्कर्ष", "रिपोर्ट",
    "इंटरनेट", "उपलब्ध", "संबंधित", "प्रासंगिक", "कहती", "कहता", "कहते",
    "बताती", "बताता", "बताते", "डालता", "डालती", "पड़ता", "पड़ती",
}
_META |= _ALWAYS_META

# Bahut aam, bahut generic shabd. Inhe poora hataana galat hoga (kabhi topic ka
# hissa hote hain), par inhe topic ka MUKHYA shabd maan lena bhi galat hai —
# isliye aadha weight.
_GENERIC = {
    "science", "scientific", "system", "systems", "technology", "technologies",
    "technical", "new", "future", "world", "human", "humans", "people",
    "problem", "problems", "solution", "solutions", "work", "working", "time",
    "year", "years", "today", "modern", "current", "possible", "possibility",
    "way", "ways", "level", "levels", "type", "types", "based",
    "civilization", "civilisation", "society",
    "विज्ञान", "वैज्ञानिक", "तकनीक", "तकनीकी", "प्रौद्योगिकी", "नई", "नया",
    "नए", "भविष्य", "दुनिया", "मानव", "मानवीय", "लोग", "सभ्यता", "समस्या",
    "समाधान", "समय", "वर्ष", "वर्षों", "साल", "आधुनिक", "वर्तमान", "संभावना",
    "संभावनाएं", "तरीका", "तरीके", "स्तर", "प्रकार",
}

# ── Devanagari -> English (research vocabulary) ──────────────────────────────
# Papers/books/datasets ka index English mein hai. Hindi term ko waise hi bhej
# dene par OpenAlex/PubMed/Zenodo 0 result dete hain — aur wo hamari kami hai,
# duniya ki nahi. Sirf wahi shabd jinka ek saaf English research-term hai.
_GLOSSARY: Dict[str, str] = {
    # energy / physics
    "ऊर्जा": "energy", "उर्जा": "energy", "बिजली": "electricity",
    "विद्युत": "electric", "सौर": "solar", "नाभिकीय": "nuclear",
    "परमाणु": "atomic", "संलयन": "fusion", "विखंडन": "fission",
    "बैटरी": "battery", "ईंधन": "fuel", "हाइड्रोजन": "hydrogen",
    "नवीकरणीय": "renewable", "पवन": "wind", "कोयला": "coal", "तेल": "oil",
    "गैस": "gas", "भंडारण": "storage", "दक्षता": "efficiency",
    "कुशल": "efficient", "असीमित": "unlimited", "स्वच्छ": "clean",
    "भौतिकी": "physics", "भौतिक": "physical", "गुरुत्वाकर्षण": "gravity",
    "क्वांटम": "quantum", "ताप": "heat", "तापमान": "temperature",
    "प्रकाश": "light", "गति": "speed", "बल": "force", "द्रव्यमान": "mass",
    "घनत्व": "density", "दबाव": "pressure", "सीमा": "limit",
    "सीमाएं": "limits", "सीमाओं": "limits", "अवरोध": "barrier",
    # chemistry / materials
    "रसायन": "chemistry", "रासायनिक": "chemical", "अणु": "molecule",
    "उत्प्रेरक": "catalyst", "धातु": "metal", "अर्धचालक": "semiconductor",
    "पदार्थ": "material", "यौगिक": "compound", "अभिक्रिया": "reaction",
    # biology / medicine
    "जीव": "biology", "जैविक": "biological", "कोशिका": "cell",
    "जीन": "gene", "आनुवंशिक": "genetic", "प्रोटीन": "protein",
    "मस्तिष्क": "brain", "तंत्रिका": "neural", "बीमारी": "disease",
    "रोग": "disease", "कैंसर": "cancer", "मधुमेह": "diabetes",
    "दवा": "drug", "औषधि": "medicine", "इलाज": "treatment",
    "उपचार": "treatment", "टीका": "vaccine", "प्रतिरक्षा": "immunity",
    "स्वास्थ्य": "health", "पोषण": "nutrition", "आहार": "diet",
    "नींद": "sleep", "व्यायाम": "exercise", "लक्षण": "symptom",
    # math / cs
    "गणित": "mathematics", "गणितीय": "mathematical", "आंकड़े": "statistics",
    "सांख्यिकी": "statistics", "प्रायिकता": "probability",
    "कंप्यूटर": "computer", "एल्गोरिदम": "algorithm", "मशीन": "machine",
    "कृत्रिम": "artificial", "बुद्धिमत्ता": "intelligence",
    "नेटवर्क": "network", "सुरक्षा": "security", "सॉफ्टवेयर": "software",
    "प्रोग्रामिंग": "programming", "मॉडल": "model", "प्रशिक्षण": "training",
    # engineering / space
    "अभियांत्रिकी": "engineering", "इंजीनियरिंग": "engineering",
    "यंत्र": "device", "उपकरण": "device", "निर्माण": "manufacturing",
    "उत्पादन": "production", "अंतरिक्ष": "space", "ग्रह": "planet",
    "तारा": "star", "ब्रह्मांड": "universe", "उपग्रह": "satellite",
    # earth / climate
    "जलवायु": "climate", "पर्यावरण": "environment", "प्रदूषण": "pollution",
    "कृषि": "agriculture", "पानी": "water", "जल": "water", "मिट्टी": "soil",
    "वन": "forest", "भोजन": "food", "फसल": "crop", "मौसम": "weather",
    # social / economy
    "अर्थशास्त्र": "economics", "अर्थव्यवस्था": "economy",
    "आर्थिक": "economic", "बाजार": "market", "निवेश": "investment",
    "मुद्रास्फीति": "inflation", "गरीबी": "poverty", "रोजगार": "employment",
    "जनसंख्या": "population", "सरकार": "government", "नीति": "policy",
    "कानून": "law", "अधिकार": "rights", "शिक्षा": "education",
    "समाज": "society", "सामाजिक": "social", "संस्कृति": "culture",
    "इतिहास": "history", "ऐतिहासिक": "historical", "युद्ध": "war",
    "धर्म": "religion", "भाषा": "language", "मनोविज्ञान": "psychology",
    "मानसिक": "mental", "व्यवहार": "behavior", "भावना": "emotion",
    "व्यक्तित्व": "personality", "प्रेरणा": "motivation",
    "दर्शन": "philosophy", "नैतिकता": "ethics", "चेतना": "consciousness",
    # generic-but-useful
    "सिद्धांत": "theory", "खोज": "discovery", "आविष्कार": "invention",
    "विकास": "development", "लागत": "cost", "मापन": "measurement",
    "प्रदर्शन": "performance",
    # generic (aadha weight milega, par English mein hona zaroori hai warna
    # Devanagari roop query mein bach jaata hai aur search 0 result deta hai)
    "तकनीक": "technology", "तकनीकी": "technical", "प्रौद्योगिकी": "technology",
    "विज्ञान": "science", "वैज्ञानिक": "scientific", "मानव": "human",
    "सभ्यता": "civilization", "दुनिया": "world", "भविष्य": "future",
    "समस्या": "problem", "समाधान": "solution", "प्रणाली": "system",
    "व्यवस्था": "system",
}

# ── Roman Hinglish -> English ────────────────────────────────────────────────
# intel Hinglish mein likhta hai ("diabetes me asar", "dawa ka nuksan"), aur
# Devanagari glossary un par nahi lagti. Bina iske "asar"/"dawa" jaise ASLI
# topic shabd seedhe PubMed ko chale jaate the — aur wahan inka koi index nahi
# hai, to 0 result. Sirf wahi shabd jinka ek saaf English research-term hai.
_GLOSSARY.update({
    "asar": "effect", "prabhav": "effect", "prabhaav": "effect",
    "ilaj": "treatment", "ilaaj": "treatment", "upchar": "treatment",
    "dawa": "drug", "dawai": "drug", "davai": "drug", "aushadhi": "medicine",
    "bimari": "disease", "bimaari": "disease", "beemari": "disease",
    "rog": "disease", "sehat": "health", "swasthya": "health",
    "khoon": "blood", "dimag": "brain", "dimaag": "brain",
    "neend": "sleep", "khana": "food", "bhojan": "food", "vajan": "weight",
    "wajan": "weight", "kasrat": "exercise", "vyayam": "exercise",
    "khatra": "risk", "fayda": "benefit", "faayda": "benefit",
    "nuksan": "harm", "nuksaan": "harm", "wajah": "cause", "karan": "cause",
    "kaaran": "cause", "urja": "energy", "oorja": "energy",
    "paani": "water", "mausam": "weather", "garmi": "heat",
    "pradushan": "pollution", "kheti": "agriculture", "fasal": "crop",
    "mehngai": "inflation", "arthvyavastha": "economy", "garibi": "poverty",
    "shiksha": "education", "sarkar": "government", "kanoon": "law",
    "bhasha": "language", "itihas": "history", "brahmand": "universe",
    "grah": "planet", "antriksh": "space",
})

# instruction-style prompt kab maanein
_LONG_TOKENS = 25          # itne se zyada content tokens = lamba prompt
_META_HITS = 3             # aur itne instruction shabd = "ye instruction hai"
_MAX_QUERY_CHARS = 200     # koi API ko isse lambi query nahi bhejni
_OPENING_TOKENS = 30       # "shuruaat" ka daayra — topic aksar yahin hota hai
_OPENING_BOOST = 1.75      # shuruaat mein aaya to score itna guna
_GENERIC_WEIGHT = 0.5      # generic shabd aadhe wazan ka

# Ye shabd 's' par khatam hote hain par plural NAHI hain — inhe kaatna matlab
# badal deta hai ("species" -> "specy" jaisa bekaar token).
_PLURAL_SAFE = {"species", "series", "analysis", "basis", "physics", "news",
                "gas", "mass", "lens", "bias", "focus", "virus", "status",
                "process", "access", "class", "less", "cross", "loss"}


def _canon(term: str) -> str:
    """
    Ek shabd ka ANDAR ka roop (grouping key): Devanagari -> English, plural ->
    singular. Ye sirf GINTI ke liye hai — bahar bhejne ke liye `_surface` dekho.

    Plural normalize karna zaroori hai warna ek hi cheez do term ban jaati hai
    aur dono ka score aadha reh jaata hai — live test mein exactly ye hua:
    "तकनीक" (-> technology) aur "technologies" (-> technologie) alag gine gaye,
    dono 0.875 par ruk gaye, aur "chemistry" jaisa ek-baar aaya field naam unse
    aage nikal gaya.

    Par ye roop hamesha asli shabd NAHI hota: "diabetes" -> "diabete",
    "series" -> "serie". Aisa shabd search API ko bhejna nuksaan hai (aur report
    mein tootela dikhta hai), isliye ye key andar hi rehti hai.
    """
    term = term.lower()
    mapped = _GLOSSARY.get(term)
    if mapped:
        return mapped
    if len(term) <= 4 or term in _PLURAL_SAFE:
        return term
    if term.endswith("ies"):          # technologies -> technology
        return term[:-3] + "y"
    if term.endswith("ics"):          # physics, mathematics — waise hi rehne do
        return term
    if term.endswith("s") and not term.endswith(("ss", "us", "is")):
        return term[:-1]
    return term


def _tokens(text: str) -> List[str]:
    """
    Content tokens. Sirf-ank wale token (jaise "100" — "100 वर्षों में") chhod
    dete hain: wo topic nahi batate aur search query mein jagah kha jaate hain.
    """
    out: List[str] = []
    for m in _TERM_RE.finditer(text or ""):
        token = m.group(0).strip("-'/").lower()
        if len(token) < 3 or token.isdigit():
            continue
        out.append(token)
    return out


def is_instruction_prompt(question: str) -> bool:
    """
    Lamba, "AI ko kaam samjhane wala" prompt hai ya seedha chhota sawaal?

    Farak zaroori hai: chhote sawaal par instruction-filter lagana nuksaan
    karega ("hypothesis testing kya hai" ka topic hi ud jaata). Isliye do
    condition ek saath: prompt lamba HO **aur** usme kai instruction shabd hon.
    """
    tokens = _tokens(normalize(question or ""))
    if len(tokens) <= _LONG_TOKENS:
        return False
    meta_hits = sum(1 for t in tokens if t in _META or _canon(t) in _META)
    return meta_hits >= _META_HITS


def scored_terms(question: str) -> List[Tuple[str, float]]:
    """(canon term, score) — sirf andar ke istemal ke liye. `topic_terms` dekho."""
    return _scored(question)[0]


def _scored(question: str) -> Tuple[List[Tuple[str, float]], Dict[str, str]]:
    """
    (sorted [(canon, score)], canon -> asli shabd) — score zyada = topic ke
    zyada kareeb.

    score(term) = SUM over har baar aane ka:
                      (generic ho to 0.5, warna 1.0)
                      x (shuruaat mein aaya to 1.75, warna 1.0)

    Bonus GUNA hota hai, JODA nahi — ye jaan-boojh kar hai. Pehle jodte the aur
    tab "मानव सभ्यता" (generic 0.5 + bonus 0.75 = 1.25) "nuclear" (1.0) se aage
    nikal jaata tha, yaani filler hi top par. Guna karne se generic shuruaat
    mein bhi 0.875 rehta hai aur asli topic 1.75 — sahi kram.

    Doosra output "surface" map hai: canon key ke saath user ne jo ASLI angrezi
    shabd likha tha. Ginti canon par hoti hai (taaki battery/batteries ek hi
    cheez rahein), par bahar asli shabd jaata hai.
    """
    text = normalize(question or "")
    if not text.strip():
        return [], {}

    instruction = is_instruction_prompt(question)
    tokens = _tokens(text)
    # "Shuruaat" = pehle ~30 content tokens. Vaakya-ke-hisaab se karna galat
    # nikla: lambe prompt mein pehli line newline par khatam ho jaati hai, to
    # "nuclear/solar/battery" (dusri line) ko bonus hi nahi milta tha.
    opening = set(tokens[:_OPENING_TOKENS])

    counts: Dict[str, float] = {}
    first_at: Dict[str, int] = {}
    surface: Dict[str, str] = {}
    for index, token in enumerate(tokens):
        if token in _STOP:
            continue
        term = _canon(token)
        if term in _STOP:
            continue
        # ye shabd kisi bhi sawaal mein topic nahi hote (aur relevance guard
        # mein "har paper match kar gaya" wala jhooth banate hain)
        if token in _ALWAYS_META or term in _ALWAYS_META:
            continue
        # baaki instruction vocabulary sirf lambe prompt mein hataao
        if instruction and (token in _META or term in _META):
            continue
        weight = _GENERIC_WEIGHT if (token in _GENERIC or term in _GENERIC) else 1.0
        if token in opening:
            weight *= _OPENING_BOOST
        counts[term] = counts.get(term, 0.0) + weight
        first_at.setdefault(term, index)
        # Asli shabd sirf tab yaad rakho jab wo Roman/angrezi ho — Devanagari
        # token search API ko bhejna 0 result laata hai (aur ek test isi ko
        # rokta hai). Aise term ke liye canon (mapped English) hi bahar jaata
        # hai.
        if _ROMAN_ONLY.match(token) and token not in _GLOSSARY:
            surface.setdefault(term, token)

    # Barabar score par ALPHABET se nahi, JAGAH se faisla — jo shabd pehle aaya
    # wo topic ke zyada kareeb hai. (Pehle alphabetical tha aur tab "battery,
    # chemistry, clean, computer" jeet jaate the aur "nuclear, solar" — jo
    # sawaal ki pehli line mein the — top-8 se bahar ho jaate the.)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], first_at[kv[0]]))
    return ordered, surface


def topic_terms(question: str, limit: int = 8) -> List[str]:
    """
    Sawaal ka asli topic — top scoring terms (English mein, jahan map ho saka).

    Ye do jagah use hota hai aur DONO jagah ek hi list hona zaroori hai:
      * search query banane mein (kya dhoondein)
      * relevance guard mein (jo mila wo isi topic ka hai ya nahi)
    Warna hum ek cheez dhoondte aur dusri cheez ko "relevant" maan lete.

    Bahar ASLI shabd jaate hain, andar ka stemmed roop nahi: pehle yahan se
    "diabetes" ki jagah "diabete" nikalta tha, aur wahi teen jagah nuksaan kar
    raha tha — PubMed/OpenAlex ko tootela shabd search karne jaata, relevance
    "technology" ko "technologies" wale title mein dhoondh nahi paati, aur user
    ko honesty report mein "diabete" dikhta. Plural ki ginti ab bhi canon par
    hoti hai (battery/batteries ek hi cheez), aur relevance khud halka stem
    karke match karta hai — isliye kuch toota nahi.
    """
    ordered, surface = _scored(question)
    terms = [surface.get(term, term) for term, _ in ordered]
    return terms[: max(1, limit)] if terms else []


def search_query(question: str, extra: Optional[List[str]] = None,
                 limit: int = 7, max_chars: int = _MAX_QUERY_CHARS) -> str:
    """
    Search-engine ke liye chhoti, topic-wali query.

    `extra` = planner ke steering words (field name, "systematic review",
    "contradictory findings") — ye AAKHIR mein jodte hain, taaki round 2/3 ki
    query sach mein alag ho.
    """
    terms = topic_terms(question, limit=limit)
    if extra:
        for word in extra:
            word = (word or "").strip()
            if word and word.lower() not in [t.lower() for t in terms]:
                terms.append(word)
    query = " ".join(terms).strip()
    if len(query) > max_chars:
        # poore word par kaato, aadhe shabd par nahi
        query = query[:max_chars].rsplit(" ", 1)[0]
    return query
