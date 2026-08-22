"""Specialist research taxonomy for mind, traditions and contested claims.

These topics need a different boundary than ordinary keyword search.  A CIA
Reading Room PDF proves that an agency retained/released a document; it does not
prove every claim inside it.  A traditional chakra text is historically real as
a tradition, but that is not the same thing as biomedical evidence.  Likewise a
conspiracy allegation, a measured frequency in hertz, a symbolic use of
"vibration", and an app-generated hypothesis must never be blended together.

The module is deterministic and network-free.  It plans legally accessible
research lanes, exact phrase matching, multilingual search anchors, official
archive queries and user-facing evidence boundaries.  It does not decide that a
claim is true and it never assigns a real-world success probability.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urlparse

from .local_language import normalize
from .multilingual_research import build_multilingual_plan


@dataclass(frozen=True)
class SpecialistProfile:
    key: str
    label: str
    signals: Tuple[str, ...]
    fields: Tuple[str, ...]
    question_types: Tuple[str, ...]
    search_seeds: Tuple[str, ...]
    source_lanes: Tuple[str, ...]
    requires_books: bool = True
    empirical_data_useful: bool = False
    archive_family: str = ""
    caution: str = ""

    def public_dict(self) -> Dict:
        payload = asdict(self)
        payload.pop("signals", None)
        return payload


PROFILES: Tuple[SpecialistProfile, ...] = (
    SpecialistProfile(
        key="mind_cognition",
        label="Mind, cognition, consciousness & human behaviour",
        signals=(
            "conscious mind", "subconscious mind", "unconscious mind",
            "consciousness", "subconscious", "unconscious", "cognition",
            "cognitive", "human behavior", "human behaviour", "brain power",
            "memory", "attention", "neuroplasticity", "dimag", "dimaag",
            "dimag tej", "दिमाग", "मस्तिष्क", "चेतना", "अवचेतन",
            "अचेतन", "मानव व्यवहार", "याददाश्त", "ध्यान",
        ),
        fields=("Cognitive Neuroscience", "Psychology", "Behavioral Science",
                "Learning Science", "Sleep & Exercise Science"),
        question_types=("psychological", "scientific"),
        search_seeds=(
            "cognitive performance memory attention systematic review",
            "sleep exercise nutrition learning neuroplasticity randomized trial",
            "cognitive enhancement harms bias placebo replication",
        ),
        source_lanes=("empirical_science", "scholarly_interpretation"),
        requires_books=False,
        empirical_data_useful=True,
        caution=("Subjective experience, philosophical theories of mind and measured "
                 "neural/behavioural outcomes must be reported separately."),
    ),
    SpecialistProfile(
        key="jung_depth_psychology",
        label="Carl Jung, analytical psychology, shadow & individuation",
        signals=(
            "carl jung", "c. g. jung", "cg jung", "jungian", "analytical psychology",
            "shadow work", "individuation", "collective unconscious", "archetype",
            "anima", "animus", "छाया कार्य", "व्यक्तित्वीकरण", "जुंग",
        ),
        fields=("History of Psychology", "Analytical Psychology", "Religious Studies",
                "Psychotherapy Research", "Cultural Studies"),
        question_types=("psychological", "historical", "philosophical"),
        search_seeds=(
            "Carl Jung primary works analytical psychology historical context",
            "Jungian psychotherapy shadow work empirical evidence review",
            "individuation criticism modern reinterpretation",
        ),
        source_lanes=("primary_historical_text", "scholarly_interpretation",
                      "empirical_science"),
        caution=("Modern social-media 'shadow work' must not be attributed to Jung "
                 "unless the primary text or reliable scholarship supports it."),
    ),
    SpecialistProfile(
        key="philosophy_metaphysics",
        label="Philosophy of mind & metaphysics",
        signals=(
            "metaphysics", "metaphysical", "ontology", "epistemology", "mind body",
            "mind-body", "free will", "nature of reality", "philosophy of mind",
            "तत्वमीमांसा", "दर्शन", "वास्तविकता", "स्वतंत्र इच्छा",
        ),
        fields=("Metaphysics", "Philosophy of Mind", "Epistemology", "Ethics",
                "History of Ideas"),
        question_types=("philosophical", "historical"),
        search_seeds=(
            "metaphysics philosophy of mind primary texts scholarly overview",
            "metaphysical claim competing theories objections",
            "philosophy of mind empirical boundary neuroscience",
        ),
        source_lanes=("primary_historical_text", "scholarly_interpretation",
                      "empirical_science"),
        caution=("A coherent philosophical argument is not automatically an empirical "
                 "finding; empirical and conceptual support need different labels."),
    ),
    SpecialistProfile(
        key="esotericism_occult_history",
        label="Esotericism, occult history, Hermetic and spiritual traditions",
        signals=(
            "esoteric", "esotericism", "occult", "occult sciences", "hermetic",
            "hermeticism", "alchemy", "mysticism", "spirituality", "spiritual",
            "divine spark", "chakra", "chakras", "seven chakras", "7 chakras",
            "kundalini", "tantra", "theosophy", "gnostic", "gnosticism",
            "गूढ़", "गुप्त विज्ञान", "रहस्यवाद", "आध्यात्मिक", "अध्यात्म",
            "चक्र", "कुंडलिनी", "तंत्र", "दिव्य चिंगारी",
        ),
        fields=("Western Esotericism", "History of Religions", "Religious Studies",
                "Anthropology", "History of Ideas", "Textual Studies"),
        question_types=("historical", "philosophical", "sociological"),
        search_seeds=(
            "Western esotericism occult history primary sources scholarship",
            "Hermeticism historical texts academic interpretation",
            "spiritual practice claim empirical evidence criticism",
        ),
        source_lanes=("traditional_belief_text", "primary_historical_text",
                      "scholarly_interpretation", "empirical_science"),
        caution=("Traditional, symbolic and spiritual claims are historically meaningful "
                 "but must not be presented as scientific fact without suitable tests."),
    ),
    SpecialistProfile(
        key="declassified_intelligence",
        label="Declassified intelligence & official records",
        signals=(
            "cia document", "cia documents", "cia reading room", "declassified",
            "freedom of information", "foia", "fbi vault", "national archives",
            "project stargate", "stargate project", "gateway process", "remote viewing",
            "cia दस्तावेज", "अवर्गीकृत", "सरकारी दस्तावेज",
        ),
        fields=("Intelligence History", "Archival Research", "Government Records",
                "Cold War History", "Source Criticism"),
        question_types=("historical", "sociological"),
        search_seeds=(
            "declassified intelligence records historical context",
            "official document provenance authorship date archival series",
            "independent historical assessment declassified claim",
        ),
        source_lanes=("official_document_record", "primary_historical_text",
                      "scholarly_interpretation"),
        archive_family="declassified",
        caution=("An official archive proves document provenance/release, not the truth "
                 "of every allegation, experiment result or opinion in that document."),
    ),
    SpecialistProfile(
        key="secret_societies_history",
        label="Freemasonry, secret societies & institutional history",
        signals=(
            "freemason", "freemasonry", "masonic", "secret society", "secret societies",
            "illuminati", "new world order", "nwo", "गुप्त समाज", "फ्रीमेसन",
            "नई विश्व व्यवस्था", "न्यू वर्ल्ड ऑर्डर",
        ),
        fields=("Institutional History", "Sociology", "Political History",
                "Religious Studies", "Archival Research"),
        question_types=("historical", "sociological"),
        search_seeds=(
            "Freemasonry secret societies institutional history primary sources",
            "secret society claim archival evidence historiography",
            "new world order allegation origins fact check primary records",
        ),
        source_lanes=("primary_historical_text", "official_document_record",
                      "scholarly_interpretation", "allegation_or_conspiracy_claim"),
        archive_family="institutions",
        caution=("Documented organizations and rituals must be separated from claims "
                 "about hidden global control for which evidence may be absent."),
    ),
    SpecialistProfile(
        key="conspiracy_claims",
        label="Conspiracy-claim analysis & misinformation research",
        signals=(
            "conspiracy", "conspiracy theory", "conspiracy theories", "cover up",
            "cover-up", "hidden agenda", "false flag", "deep state", "new world order",
            "साजिश", "षड्यंत्र", "छिपा एजेंडा",
        ),
        fields=("Misinformation Research", "Social Psychology", "History",
                "Political Science", "Media Studies", "OSINT Methods"),
        question_types=("sociological", "psychological", "historical"),
        search_seeds=(
            "conspiracy claim primary evidence provenance timeline",
            "conspiracy theory alternative explanations misinformation research",
            "claim falsification missing evidence independent investigation",
        ),
        source_lanes=("allegation_or_conspiracy_claim", "official_document_record",
                      "scholarly_interpretation"),
        archive_family="claims",
        caution=("Popularity, repetition, secrecy language and absence of disproof do "
                 "not establish an allegation as fact."),
    ),
    SpecialistProfile(
        key="frequency_claims",
        label="Measured frequency vs spiritual 'frequency' claims",
        signals=(
            "frequency", "frequencies", "hertz", " hz", "binaural", "brainwave",
            "solfeggio", "vibration", "vibrational", "healing frequency",
            "आवृत्ति", "हर्ट्ज", "कंपन", "हीलिंग फ्रीक्वेंसी",
        ),
        fields=("Physics", "Signal Processing", "Auditory Neuroscience",
                "Psychology", "History of Spiritual Movements"),
        question_types=("philosophical",),
        search_seeds=(
            "frequency hertz measurement signal parameters mechanism",
            "binaural beats cognition systematic review placebo controlled",
            "healing frequency claim evidence adverse effects criticism",
        ),
        source_lanes=("measured_frequency_evidence", "traditional_belief_text",
                      "scholarly_interpretation"),
        requires_books=False,
        empirical_data_useful=True,
        caution=("Frequency measured in hertz needs a signal, amplitude, exposure and "
                 "outcome; symbolic 'vibration' language is a separate claim type."),
    ),
)


_PROFILE_BY_KEY = {profile.key: profile for profile in PROFILES}
_ARCHIVE_SITES = (
    "site:cia.gov/readingroom",
    "site:archives.gov",
    "site:vault.fbi.gov",
    "site:govinfo.gov",
)
_OFFICIAL_HOST_SUFFIXES = (
    "cia.gov", "archives.gov", "fbi.gov", "govinfo.gov", "gao.gov",
    "congress.gov", "loc.gov", "defense.gov", "state.gov",
)
_AMBIGUOUS_TERMS = ("pix etma", "pix atma")
_MAX_QUERY_CHARS = 200


LANES: Dict[str, Dict[str, str]] = {
    "empirical_science": {
        "label": "Scientific / empirical evidence",
        "rule": "Measured outcomes, method, controls, replication and limitations are required.",
    },
    "measured_frequency_evidence": {
        "label": "Measured frequency evidence",
        "rule": "Hertz, signal, amplitude/exposure, measurement method and outcome stay explicit.",
    },
    "official_document_record": {
        "label": "Official / declassified document record",
        "rule": "The archive can establish provenance or release; document contents are not automatically true.",
    },
    "primary_historical_text": {
        "label": "Primary historical text",
        "rule": "Shows what an author/institution wrote in context, not automatic present-day truth.",
    },
    "traditional_belief_text": {
        "label": "Traditional / spiritual teaching",
        "rule": "Reported as a tradition, belief or practice; not relabelled as biomedical/scientific fact.",
    },
    "scholarly_interpretation": {
        "label": "Scholarly interpretation / secondary analysis",
        "rule": "Interpretation is attributed and kept distinct from primary text and empirical result.",
    },
    "allegation_or_conspiracy_claim": {
        "label": "Allegation / conspiracy claim",
        "rule": "Claim, provenance, corroboration, alternatives and disconfirming evidence are shown separately.",
    },
    "secondary_context": {
        "label": "Secondary web context",
        "rule": "Useful for leads and context; weak for establishing a contested claim on its own.",
    },
    "app_original_hypothesis": {
        "label": "App-original research hypothesis",
        "rule": "Always untested, separated from sources, with assumptions, counter-evidence and falsification test.",
    },
    "unknown_unresolved": {
        "label": "Unknown / unresolved",
        "rule": "Unclear terms and unsupported gaps stay unknown instead of receiving an invented meaning.",
    },
}


def _unique(values: Iterable[str], limit: int = 30) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= limit:
            break
    return out


def _bounded(value: str) -> str:
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(clean) <= _MAX_QUERY_CHARS:
        return clean
    return clean[:_MAX_QUERY_CHARS].rsplit(" ", 1)[0].strip()


def phrase_hit(text: str, phrase: str) -> bool:
    """Exact-enough phrase hit; ``physics`` must not match ``metaphysics``."""
    hay = unicodedata.normalize("NFKC", normalize(text or "")).casefold()
    needle = unicodedata.normalize("NFKC", phrase or "").casefold().strip()
    if not needle:
        return False
    if re.search(r"[a-z0-9]", needle):
        escaped = re.escape(needle).replace(r"\ ", r"[\s\-_]+")
        return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", hay))
    return needle in hay


def detect_profiles(question: str) -> List[SpecialistProfile]:
    found: List[SpecialistProfile] = []
    for profile in PROFILES:
        if not any(phrase_hit(question, signal) for signal in profile.signals):
            continue
        if profile.key == "frequency_claims":
            # "frequency" and "vibration" are ordinary engineering/signal
            # terms too.  Do not hijack a motor-bearing or filter question into
            # the contested spiritual/healing lane unless a measured-audio or
            # spiritual/health context is explicitly present.
            context = (
                "hz", "hertz", "khz", "mhz", "binaural", "brainwave",
                "solfeggio", "healing", "sound therapy", "audio frequency",
                "spiritual frequency", "spiritual vibration", "meditation frequency",
                "chakra frequency", "528", "432", "हर्ट्ज", "हीलिंग",
                "आध्यात्मिक आवृत्ति", "आध्यात्मिक कंपन",
            )
            if not any(phrase_hit(question, signal) for signal in context):
                continue
        found.append(profile)
    return found


def _measured_frequency_intent(question: str) -> bool:
    q = unicodedata.normalize("NFKC", normalize(question or "")).casefold()
    return bool(re.search(
        r"(?<![a-z0-9])(?:hz|hertz|khz|mhz|eeg|binaural|brainwave|signal|"
        r"हर्ट्ज|आवृत्ति)(?![a-z0-9])", q))


def specialist_classification(question: str) -> Dict:
    profiles = detect_profiles(question)
    fields = _unique(field for p in profiles for field in p.fields)
    qtypes = _unique(kind for p in profiles for kind in p.question_types)
    if any(p.key == "frequency_claims" for p in profiles) and _measured_frequency_intent(question):
        qtypes = _unique([*qtypes, "scientific"])
    unknown_terms = [term for term in _AMBIGUOUS_TERMS if phrase_hit(question, term)]
    return {
        "active": bool(profiles),
        "profile_keys": [profile.key for profile in profiles],
        "profile_labels": [profile.label for profile in profiles],
        "relevant_fields": fields,
        "question_types": qtypes,
        "needs_books": any(profile.requires_books for profile in profiles),
        "empirical_data_useful": any(profile.empirical_data_useful for profile in profiles),
        "requires_official_archives": any(profile.archive_family for profile in profiles),
        "expected_lanes": _unique(lane for p in profiles for lane in p.source_lanes),
        "cautions": [profile.caution for profile in profiles if profile.caution],
        "unknown_terms": unknown_terms,
    }


def specialist_queries(question: str, base_query: str, round_no: int = 1,
                       limit: int = 4) -> List[str]:
    profiles = detect_profiles(question)
    if not profiles:
        return []
    seeds = _unique(seed for profile in profiles for seed in profile.search_seeds)
    base = _bounded(base_query)
    if round_no <= 1:
        candidates = [base, *seeds[:2], f"{base} counter evidence criticism limitations"]
    elif round_no == 2:
        candidates = [
            f"{base} systematic review methodology replication",
            *seeds[1:3],
            f"{base} alternative explanations disconfirming evidence",
        ]
    elif round_no == 3:
        candidates = [
            f"{base} primary sources historical context provenance",
            f"{base} scholarly criticism historiography",
            f"{base} failed replication null result placebo bias",
            f"{base} what evidence would falsify the claim",
        ]
    else:
        candidates = [
            f"{base} unresolved questions strongest evidence",
            f"{base} independent corroboration original documents",
            f"{base} boundary empirical symbolic interpretation",
            f"{base} adversarial review competing explanation",
        ]
    return _unique((_bounded(item) for item in candidates if item), limit=max(1, limit))


def official_archive_queries(question: str, base_query: str, limit: int = 3) -> List[str]:
    classification = specialist_classification(question)
    if not classification["requires_official_archives"]:
        return []
    topic = _bounded(base_query) or _bounded(question)
    return _unique((_bounded(f"{site} {topic}") for site in _ARCHIVE_SITES), limit=limit)


def build_specialist_plan(question: str, base_query: str) -> Dict:
    classification = specialist_classification(question)
    profiles = [_PROFILE_BY_KEY[key] for key in classification["profile_keys"]]
    english_anchors = _unique(seed for profile in profiles for seed in profile.search_seeds)
    multilingual = build_multilingual_plan(question, base_query, english_anchors[:3])
    archive_queries = official_archive_queries(question, base_query)
    return {
        **classification,
        "profiles": [profile.public_dict() for profile in profiles],
        "multilingual": multilingual,
        "book_queries": multilingual.get("book_queries", []),
        "official_archive_queries": archive_queries,
        "official_archive_scope": list(_ARCHIVE_SITES) if archive_queries else [],
        "legal_access_only": True,
        "claim_boundary_rules": [
            "Official document existence/provenance is not proof that every statement inside is true.",
            "Traditional or spiritual teaching is not empirical science unless suitable empirical evidence exists.",
            "Conspiracy allegation is not fact; repetition and absence of disproof are not confirmation.",
            "Measured frequency in hertz is separate from symbolic/spiritual use of 'frequency' or 'vibration'.",
            "App-original hypotheses remain untested and appear only in their own hypothesis section.",
        ],
        "hypothesis_policy": {
            "separate_output_required": True,
            "status": "UNTESTED HYPOTHESIS",
            "must_include": [
                "source-grounded starting facts", "gap", "assumptions",
                "supporting evidence", "counter-evidence", "measurable prediction",
                "required experiment or simulation", "falsification condition",
            ],
            "truth_probability_claim_allowed": False,
            "global_novelty_claim_allowed": False,
        },
    }


def prompt_block(plan: Dict) -> str:
    specialist = (plan or {}).get("specialist") if isinstance(plan, dict) else None
    if not isinstance(specialist, dict) or not specialist.get("active"):
        return ""
    labels = ", ".join(specialist.get("profile_labels") or [])
    cautions = "\n".join(f"- {item}" for item in specialist.get("cautions", [])[:5])
    multilingual = specialist.get("multilingual") or {}
    language_status = str(multilingual.get("translation_status") or "not_recorded")
    language_policy = str(multilingual.get("full_text_language_policy") or "").strip()
    unknown = specialist.get("unknown_terms") or []
    unknown_rule = (
        "\n- In unclear terms ka meaning invent mat karo: " + ", ".join(unknown)
        if unknown else ""
    )
    return f"""SPECIALIST EVIDENCE BOUNDARY (mandatory)
Active lenses: {labels}
- Scientific findings, official documents, historical texts, traditions,
  interpretations and allegations ko alag-alag likho; ek doosre ka proof mat banao.
- CIA/FBI/NARA document ke liye 'document mein likha/released hua' kehna allowed hai;
  uske andar ka paranormal/political claim automatically established nahi hai.
- Hertz wali measured frequency ko symbolic/spiritual vibration se alag rakho.
- App ki nayi hypothesis sirf 'Humari Hypotheses' mein, UNTESTED label ke saath.
- Unknown ko unknown rakho; 90–95% success/truth probability invent mat karo.
- Language status: {language_status}. {language_policy}
{cautions}{unknown_rule}"""


def _host(source) -> str:
    try:
        return (urlparse(str(getattr(source, "url", "") or "")).hostname or "").lower()
    except Exception:
        return ""


def _is_official(source) -> bool:
    host = _host(source)
    return any(host == suffix or host.endswith("." + suffix)
               for suffix in _OFFICIAL_HOST_SUFFIXES)


def source_lane(source, active_profile_keys: Sequence[str]) -> str:
    if _is_official(source):
        return "official_document_record"
    kind_obj = getattr(source, "source_type", "")
    kind = str(getattr(kind_obj, "value", kind_obj) or "").lower()
    keys = set(active_profile_keys or [])
    title_text = " ".join((
        str(getattr(source, "title", "") or ""),
        str(getattr(source, "snippet", "") or "")[:500],
    ))
    if kind == "dataset":
        return "empirical_science"
    if kind == "paper":
        if "frequency_claims" in keys and _measured_frequency_intent(title_text):
            return "measured_frequency_evidence"
        return (
            "empirical_science"
            if keys & {"mind_cognition", "frequency_claims"}
            else "scholarly_interpretation"
        )
    if kind == "book":
        if keys & {"esotericism_occult_history"}:
            return "traditional_belief_text"
        return "primary_historical_text"
    if kind == "document":
        return "primary_historical_text"
    return "secondary_context"


def build_evidence_lane_report(question: str, plan: Dict, pack) -> Dict:
    specialist = (plan or {}).get("specialist") if isinstance(plan, dict) else None
    if not isinstance(specialist, dict):
        specialist = build_specialist_plan(question, question)
    if not specialist.get("active"):
        return {"active": False, "profiles": [], "lanes": []}

    buckets: Dict[str, List[str]] = {}
    for source in list(getattr(pack, "sources", []) or []):
        lane = source_lane(source, specialist.get("profile_keys", []))
        source_id = str(getattr(source, "source_id", "") or "").strip()
        if source_id:
            buckets.setdefault(lane, []).append(source_id)

    expected = _unique([
        *specialist.get("expected_lanes", []),
        *buckets.keys(),
        "app_original_hypothesis",
        *(("unknown_unresolved",) if specialist.get("unknown_terms") else ()),
    ])
    rows = []
    for key in expected:
        spec = LANES.get(key, LANES["unknown_unresolved"])
        ids = _unique(buckets.get(key, []), limit=100)
        rows.append({
            "key": key,
            "label": spec["label"],
            "rule": spec["rule"],
            "source_ids": ids,
            "source_count": len(ids),
        })
    return {
        "active": True,
        "profiles": specialist.get("profiles", []),
        "profile_keys": specialist.get("profile_keys", []),
        "profile_labels": specialist.get("profile_labels", []),
        "lanes": rows,
        "claim_boundary_rules": specialist.get("claim_boundary_rules", []),
        "hypothesis_policy": specialist.get("hypothesis_policy", {}),
        "multilingual": specialist.get("multilingual", {}),
        "official_archive_queries": specialist.get("official_archive_queries", []),
        "unknown_terms": specialist.get("unknown_terms", []),
    }


def render_evidence_lane_report(report: Dict) -> str:
    if not isinstance(report, dict) or not report.get("active"):
        return ""
    lines = ["## Evidence ki alag-alag lanes"]
    for row in report.get("lanes", []):
        if not isinstance(row, dict):
            continue
        count = int(row.get("source_count") or 0)
        ids = ", ".join(row.get("source_ids") or [])
        found = f"{count} source" + (f" ({ids})" if ids else "")
        lines.append(
            f"- **{row.get('label', 'Evidence lane')}:** {found}. "
            f"{row.get('rule', '')}".strip()
        )
    unknown = report.get("unknown_terms") or []
    if unknown:
        lines.append(
            "- **Unclear term:** " + ", ".join(str(item) for item in unknown)
            + ". Iska meaning guess nahi kiya gaya; clarification milne tak unknown hai."
        )
    lines.append(
        "\n**App ki apni research hypothesis boundary:** Nayi possibilities sirf "
        "**Humari Hypotheses** section mein dikhengi. Wo cited sources ka direct "
        "conclusion nahi, UNTESTED app-generated synthesis hain; unke saath test aur "
        "galat sabit karne ki condition zaroori hai."
    )
    return "\n".join(lines)
