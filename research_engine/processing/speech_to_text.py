"""
SpeechToTextProcessor — Spec Section 5 (Video/Audio Pipeline, local STT)

TranscriptProcessor pehle se maujood transcript/subtitle FILES (.vtt/.srt/.txt)
ko timestamped chunks banata hai. Ye module ek kadam aage jaata hai: jab user ke
paas sirf AUDIO ho (koi caption file na ho), to use LOCALLY transcribe karta hai
aur wahi timestamped cue-shape ({"start","text"}) deta hai jise
TranscriptProcessor.chunk() seedhe citation locator ("12:30") mein badal deta
hai. Yaani transcription aur citation ek hi machinery se guzarte hain.

Ye module JAAN-BOOJH KAR "optional" hai (bilkul OCRProcessor ki tarah):
    * Local Whisper bhaari hai (model weights + CPU/GPU compute). Isliye ye
      requirements.txt mein NAHI hai — requirements-optional.txt mein hai.
    * Do backends support hote hain, pehle jo mile:
        1. faster-whisper  (halka, CTranslate2 — CPU par int8, torch zaroori nahi)
        2. openai-whisper   (bhaari, torch chahiye)
    * Dono mein se koi bhi install na ho, to ye module CHUP-CHAAP fail nahi hota
      — saaf batata hai ki STT unavailable hai aur kaise install karna hai
      (OCRProcessor jaisa hi honest degradation).

HONESTY (Spec Section 5 + 13 + 18):
    * LOCAL + FREE hai — koi API key, koi per-call quota nahi (Gemini budget
      alag hai, ye use nahi karta). Par CPU/RAM/time kharch hota hai, aur pehli
      baar model weights download hote hain (ek baar internet chahiye).
    * Transcription MACHINE KA BEST GUESS hai, verbatim sach nahi. Accent,
      background noise, domain terms par galtiyan aati hain. Isliye har result
      par disclaimer lagta hai aur chunk header mein "(auto-transcribed)" jaata
      hai — taaki citation kabhi "insaan ne likha" jaisa na lage.
    * Ye kisi platform se video/audio DOWNLOAD nahi karta aur koi protection
      bypass nahi karta — user apni audio file khud deta hai.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

# spec: model chhota rakho taaki laptop par chal sake; user .env se badha sake
_DEFAULT_MODEL = "base"
_SUPPORTED_EXT = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma",
                  ".mp4", ".mov", ".mkv", ".webm", ".m4b", ".opus")

DISCLAIMER = (
    "Ye transcript LOCAL speech-to-text (Whisper) ka best guess hai, verbatim "
    "sach nahi — accent/noise/domain terms par galtiyan sambhav hain. Ise "
    "'machine transcription' ki tarah treat karein, kisi insaan ka likha hua "
    "nahi. Citations timestamp ke saath aati hain."
)

INSTALL_HINT = (
    "Local audio transcription ke liye in dono mein se ek chahiye (dono FREE + "
    "offline hain, koi API key nahi):\n"
    "  A) Halka rasta:  pip install faster-whisper\n"
    "  B) Ya:           pip install openai-whisper   (torch bhaari hai)\n"
    "Pehli baar model weights download honge (ek baar internet chahiye). "
    "Model size .env mein WHISPER_MODEL se badal sakte hain "
    "(tiny/base/small/medium; default 'base'). CPU par WHISPER_COMPUTE_TYPE=int8 "
    "sabse halka hai."
)


def _cues_from_segments(segments) -> List[Dict]:
    """
    Whisper (dono backends) ke segments ko TranscriptProcessor wali cue-shape
    [{"start": int_seconds, "text": str}] mein badlo.

    Ye JAAN-BOOJH KAR alag aur pure hai (koi model, koi network) — taaki offline
    test isse bina Whisper install kiye verify kar sake. Segment ya to dict ho
    sakta hai ({"start","text"}) ya object with .start/.text (faster-whisper) —
    dono handle karta hai, aur khaali text skip kar deta hai.
    """
    cues: List[Dict] = []
    for seg in segments or []:
        if isinstance(seg, dict):
            start = seg.get("start", 0)
            text = seg.get("text", "")
        else:                                    # faster-whisper Segment object
            start = getattr(seg, "start", 0)
            text = getattr(seg, "text", "")
        text = (text or "").strip()
        if not text:
            continue
        try:
            start_int = int(float(start))
        except (TypeError, ValueError):
            start_int = 0
        cues.append({"start": max(0, start_int), "text": text})
    return cues


class SpeechToTextProcessor:
    name = "speech_to_text"

    def __init__(self, model_size: str = "", lang: Optional[str] = None):
        # .env > constructor arg > default — teeno honest priority mein
        self.model_size = (model_size or os.getenv("WHISPER_MODEL", "")
                           or _DEFAULT_MODEL)
        self.lang = lang
        self.last_error: str = ""

    # ── availability (kabhi exception nahi) ───────────────────────────────────
    def available(self) -> Dict:
        """
        {"ok": bool, "backend": "faster-whisper"|"openai-whisper"|"", "reason": str}
        Koi bhi backend mile to ok=True. Dono na hon to honest install hint.
        """
        try:
            import faster_whisper  # noqa: F401
            return {"ok": True, "backend": "faster-whisper", "reason": ""}
        except Exception:
            pass
        try:
            import whisper  # noqa: F401  (openai-whisper)
            return {"ok": True, "backend": "openai-whisper", "reason": ""}
        except Exception:
            pass
        return {"ok": False, "backend": "",
                "reason": f"koi local STT backend install nahi hai. {INSTALL_HINT}"}

    # ── transcription ─────────────────────────────────────────────────────────
    def transcribe(self, audio_path: str, lang: Optional[str] = None) -> Dict:
        """
        audio/video file ko locally transcribe karo.
        Returns {"ok","error","backend","cues":[{"start","text"}],"disclaimer","note"}
        cues ka shape TranscriptProcessor jaisa hai — isliye chunk() seedhe chalega.
        """
        status = self.available()
        if not status["ok"]:
            return {"ok": False, "error": status["reason"], "backend": "",
                    "cues": [], "disclaimer": DISCLAIMER, "note": ""}

        if not os.path.exists(audio_path):
            return {"ok": False, "error": f"file nahi mili: {audio_path}",
                    "backend": status["backend"], "cues": [],
                    "disclaimer": DISCLAIMER, "note": ""}

        language = lang if lang is not None else self.lang
        backend = status["backend"]
        try:
            if backend == "faster-whisper":
                cues = self._faster_whisper(audio_path, language)
            else:
                cues = self._openai_whisper(audio_path, language)
        except Exception as exc:
            return {"ok": False,
                    "error": f"transcription fail ({backend}): "
                             f"{type(exc).__name__}: {exc}",
                    "backend": backend, "cues": [], "disclaimer": DISCLAIMER,
                    "note": ""}

        return {"ok": bool(cues),
                "error": "" if cues else "transcript khaali nikla (audio mein "
                                          "speech nahi mili ya format samajh nahi aaya)",
                "backend": backend, "cues": cues, "disclaimer": DISCLAIMER,
                "note": f"{backend} ({self.model_size}) se {len(cues)} segments"}

    def _faster_whisper(self, audio_path: str, language: Optional[str]) -> List[Dict]:
        from faster_whisper import WhisperModel
        device = os.getenv("WHISPER_DEVICE", "cpu")
        compute = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        model = WhisperModel(self.model_size, device=device, compute_type=compute)
        segments, _info = model.transcribe(audio_path, language=language)
        # segments ek generator hai — list mein khinchte hi transcription chalti hai
        return _cues_from_segments(list(segments))

    def _openai_whisper(self, audio_path: str, language: Optional[str]) -> List[Dict]:
        import whisper
        model = whisper.load_model(self.model_size)
        result = model.transcribe(audio_path, language=language)
        return _cues_from_segments(result.get("segments") or [])

    # ── transcribe + chunk (citation-ready, ek hi call) ───────────────────────
    def process_file(self, audio_path: str, chunk_seconds: int = 120,
                     lang: Optional[str] = None) -> Dict:
        """
        transcribe → timestamped chunks. Shape TranscriptProcessor.process_file
        jaisa hi ({"ok","error","chunks","text","source"}) taaki ingest path ek
        jaisa rahe. Har chunk header mein "(auto-transcribed)" lagta hai.
        """
        result = self.transcribe(audio_path, lang=lang)
        if not result["ok"]:
            return {"ok": False, "error": result["error"], "chunks": [],
                    "text": "", "source": os.path.basename(audio_path),
                    "disclaimer": DISCLAIMER}

        # TranscriptProcessor ka chunk() reuse karo — DRY + wahi citation format
        from .transcript_processor import TranscriptProcessor
        source = os.path.basename(audio_path) + " (auto-transcribed)"
        chunks = TranscriptProcessor().chunk(result["cues"], source, chunk_seconds)
        text = "\n\n".join(f"{c['header']}\n{c['text']}" for c in chunks)
        return {"ok": True, "error": "", "chunks": chunks, "text": text,
                "source": source, "backend": result["backend"],
                "disclaimer": DISCLAIMER,
                "duration_note": f"{len(result['cues'])} segments, "
                                 f"{len(chunks)} timestamped blocks "
                                 f"({result['backend']}, model={self.model_size})"}

    def note(self, result: Dict) -> str:
        if not result.get("ok"):
            return f"Local transcription nahi chali — {result.get('error', '')}"
        return (f"Audio locally transcribe hui ({result.get('backend', '')}, "
                f"model={self.model_size}). {DISCLAIMER}")
