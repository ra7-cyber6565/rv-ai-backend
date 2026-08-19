"""
Speech-to-text processor using OpenAI Whisper (local, offline).

Spec Section 5 ka missing piece — audio/video transcript generation.
Pehle ye stub file thi, ab poori tarah ready hai.

OPTIONAL DEPENDENCY:
    pip install openai-whisper

    Agar ye installed nahi hai, to ye module gracefully fail hota hai
    (ImportError) aur upload endpoint us file ko reject kar deta hai.
    Free-tier laptop par ye heavy hai (model download ~3GB), isliye
    requirements-optional.txt mein rakha hai.
"""
from __future__ import annotations

import os
import tempfile
from typing import Dict, List, Optional


def _whisper_available() -> bool:
    """Check if whisper is installed."""
    try:
        import whisper
        return True
    except ImportError:
        return False


def transcribe_audio(file_path: str, language: Optional[str] = None) -> Dict:
    """
    Audio/video file se transcript nikalo using Whisper.

    Args:
        file_path: Audio file ka path (.mp3, .wav, .m4a, etc)
        language: Optional language code (hi, en, etc). None = auto-detect

    Returns:
        {
            "ok": bool,
            "text": str,           # Full transcript
            "chunks": List[Dict], # Timestamped segments
            "language": str,      # Detected/specified language
            "error": str,
        }
    """
    if not _whisper_available():
        return {
            "ok": False,
            "error": "openai-whisper not installed. Install: pip install openai-whisper",
            "text": "",
            "chunks": [],
        }

    try:
        import whisper

        # Use "base" model (good balance of speed/accuracy, ~140MB)
        # Options: tiny, base, small, medium, large
        model = whisper.load_model("base")

        result = model.transcribe(
            file_path,
            language=language,
            task="transcribe",  # 'translate' would convert to English
            fp16=False,         # CPU compatibility
        )

        # Convert to our format
        chunks = []
        for segment in result.get("segments", []):
            chunks.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"].strip(),
                "locator": f"{int(segment['start'] // 60)}:{int(segment['start'] % 60):02d}",
            })

        return {
            "ok": True,
            "text": result.get("text", "").strip(),
            "chunks": chunks,
            "language": result.get("language", language or "unknown"),
            "error": "",
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "text": "",
            "chunks": [],
        }


def transcribe_to_vtt(file_path: str, output_path: Optional[str] = None,
                     language: Optional[str] = None) -> Dict:
    """
    Audio file se VTT subtitle file banao.

    Returns:
        {
            "ok": bool,
            "vtt_path": str,  # Generated VTT file path
            "error": str,
        }
    """
    result = transcribe_audio(file_path, language)
    if not result["ok"]:
        return {"ok": False, "vtt_path": "", "error": result["error"]}

    if not output_path:
        output_path = os.path.join(tempfile.gettempdir(),
                                   f"transcript_{os.path.basename(file_path)}.vtt")

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for i, chunk in enumerate(result["chunks"], 1):
                start = chunk["start"]
                end = chunk["end"]
                # VTT format: HH:MM:SS.mmm
                start_time = f"{int(start // 3600):02d}:{int((start % 3600) // 60):02d}:{start % 60:06.3f}"
                end_time = f"{int(end // 3600):02d}:{int((end % 3600) // 60):02d}:{end % 60:06.3f}"
                f.write(f"{i}\n{start_time} --> {end_time}\n{chunk['text']}\n\n")

        return {"ok": True, "vtt_path": output_path, "error": ""}

    except Exception as exc:
        return {"ok": False, "vtt_path": "", "error": str(exc)[:200]}
