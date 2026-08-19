"""
TranscriptProcessor — Spec Section 5 (Video/Audio Pipeline)

Imaandaar scope (Spec Section 3 + 13):
    * Ye module video download NAHI karta, aur kisi platform ka protection
      bypass NAHI karta.
    * Primary raasta: user ke paas jo transcript/subtitle file hai (.vtt/.srt/.txt)
      usko timestamped chunks mein todna, taaki citation "12:30" ke saath ban sake.
    * Optional raasta: publicly available captions (youtube-transcript-api).
      Ye library free hai, par platform ke Terms of Service ka dhyan rakhna
      user ki zimmedaari hai — isliye ye by default OFF hai
      (enable karne ke liye .env mein ALLOW_YT_TRANSCRIPT=true).
    * Audio se transcript banana (speech-to-text) is system mein nahi hai. Agar
      chahiye to local Whisper chahiye hoga — wo bhaari hai, isliye abhi nahi.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")
_SRT_INDEX_RE = re.compile(r"^\d+$")
_CHUNK_SECONDS = 120          # 2 minute ke blocks — citation ke liye theek hai


def _seconds(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def _stamp(total: int) -> str:
    hours, rest = divmod(max(0, total), 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class TranscriptProcessor:
    name = "transcript"

    # ── subtitle file parsing ────────────────────────────────────────────────
    def parse_file(self, file_path: str) -> Dict:
        result: Dict = {"ok": False, "error": "", "cues": [], "source": ""}
        if not os.path.exists(file_path):
            result["error"] = f"file nahi mili: {file_path}"
            return result

        result["source"] = os.path.basename(file_path)
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except Exception as exc:
            result["error"] = f"file padhi nahi gayi: {type(exc).__name__}: {exc}"
            return result

        extension = os.path.splitext(file_path)[1].lower()
        if extension in (".vtt", ".srt"):
            result["cues"] = self._parse_cues(raw)
        else:
            # plain text transcript — timestamps nahi hain
            text = raw.strip()
            result["cues"] = [{"start": 0, "text": text}] if text else []

        result["ok"] = bool(result["cues"])
        if not result["ok"] and not result["error"]:
            result["error"] = "transcript khaali tha ya format samajh nahi aaya"
        return result

    def _parse_cues(self, raw: str) -> List[Dict]:
        cues: List[Dict] = []
        current_start: Optional[int] = None
        buffer: List[str] = []

        def flush():
            if current_start is not None and buffer:
                text = " ".join(buffer).strip()
                if text:
                    cues.append({"start": current_start, "text": text})

        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.upper().startswith("WEBVTT") or stripped.startswith("NOTE"):
                continue
            if "-->" in stripped:
                flush()
                buffer = []
                match = _TIME_RE.search(stripped)
                if match:
                    current_start = _seconds(match.group(1), match.group(2), match.group(3))
                else:
                    short = re.search(r"(\d{1,2}):(\d{2})[.,](\d{1,3})", stripped)
                    current_start = (int(short.group(1)) * 60 + int(short.group(2))
                                     if short else 0)
                continue
            if _SRT_INDEX_RE.match(stripped):
                continue
            # HTML/VTT tags hataao
            buffer.append(re.sub(r"<[^>]+>", "", stripped))

        flush()
        return cues

    # ── timestamped chunks (citation ke liye) ────────────────────────────────
    def chunk(self, cues: List[Dict], source_name: str,
              chunk_seconds: int = _CHUNK_SECONDS) -> List[Dict]:
        """
        Returns [{"locator": "12:30–14:30", "text": "...",
                  "header": "[Source: name, 12:30]"}]
        """
        chunks: List[Dict] = []
        if not cues:
            return chunks

        block_start = cues[0].get("start", 0)
        block_text: List[str] = []
        last_start = block_start

        for cue in cues:
            start = cue.get("start", 0)
            if start - block_start >= chunk_seconds and block_text:
                chunks.append(self._make_chunk(source_name, block_start, last_start,
                                               block_text))
                block_start = start
                block_text = []
            block_text.append(cue.get("text", ""))
            last_start = start

        if block_text:
            chunks.append(self._make_chunk(source_name, block_start, last_start, block_text))
        return chunks

    def _make_chunk(self, source_name: str, start: int, end: int,
                    parts: List[str]) -> Dict:
        locator = _stamp(start) if start == end else f"{_stamp(start)}–{_stamp(end)}"
        text = " ".join(p for p in parts if p).strip()
        return {
            "locator": locator,
            "text": text,
            "header": f"[Source: {source_name}, {_stamp(start)}]",
        }

    def process_file(self, file_path: str, chunk_seconds: int = _CHUNK_SECONDS) -> Dict:
        parsed = self.parse_file(file_path)
        if not parsed["ok"]:
            return {"ok": False, "error": parsed["error"], "chunks": [], "text": ""}
        chunks = self.chunk(parsed["cues"], parsed["source"], chunk_seconds)
        text = "\n\n".join(f"{c['header']}\n{c['text']}" for c in chunks)
        return {"ok": True, "error": "", "chunks": chunks, "text": text,
                "source": parsed["source"], "duration_note":
                    f"{len(parsed['cues'])} cues, {len(chunks)} timestamped blocks"}

    # ── optional: public captions ────────────────────────────────────────────
    def youtube_captions(self, video_id: str) -> Dict:
        """
        Default OFF. Enable karne ke liye .env mein ALLOW_YT_TRANSCRIPT=true.
        Library free hai (koi API key nahi), par platform ToS ka dhyan user ka.
        """
        if os.getenv("ALLOW_YT_TRANSCRIPT", "").lower() not in ("1", "true", "yes"):
            return {"ok": False, "error": "YouTube captions disabled hai. Enable karne ke "
                                          "liye .env mein ALLOW_YT_TRANSCRIPT=true karein "
                                          "(platform ToS aap ki zimmedaari).",
                    "cues": []}
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # lazy, optional
        except Exception as exc:
            return {"ok": False, "error": f"youtube-transcript-api install nahi hai ({exc}) "
                                          f"— pip install youtube-transcript-api",
                    "cues": []}
        try:
            raw = YouTubeTranscriptApi.get_transcript(video_id)
        except Exception as exc:
            return {"ok": False, "error": f"captions nahi mile: {type(exc).__name__}: {exc}",
                    "cues": []}
        cues = [{"start": int(item.get("start", 0)), "text": item.get("text", "")}
                for item in raw or []]
        return {"ok": bool(cues), "error": "" if cues else "captions khaali the", "cues": cues}
