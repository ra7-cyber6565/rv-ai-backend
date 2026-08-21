"""
Free API key pool — ek key ka quota khatam ho jaaye to kaam rukna nahi chahiye.

Asli dikkat (intel, 2026-08-21): "gemini ko call krte h to quota khatam ho jaata
h ... iska quota khatam ho gya, ye kaam nhi kiya, iss wajah se jawab thoda week
rah gya" — yaani quota khatam hona SIRF ek error nahi tha, wo jawab ki QUALITY
kha jaata tha (ek reasoning pass gir gaya to poora section gayab).

Iska pehla ilaaj yahi module hai: Google ka free tier PER PROJECT/KEY hota hai,
isliye do-teen FREE key (alag-alag AI Studio project se) rakhne par ek ka din ka
quota khatam hone ke baad doosri se kaam chalta rehta hai.

₹0 rule: yahan koi paid cheez nahi hai. Ye module khud koi key nahi banata, koi
network call nahi karta — sirf env se jo free key mili hain unhe kataar mein
lagata hai. Ek hi key ho to behaviour bilkul purana rehta hai.

SECURITY: is module se key ki VALUE kabhi bahar nahi jaati — `label()` sirf
"free key #2" jaisa naam deta hai. Log, notes, audit, error — sab jagah wahi
naam jaata hai, kabhi asli key nahi.

Env (jitni ho utni — ek bhi zaroori nahi ki teen ho):
    GEMINI_API_KEY            <- pehli (purani wali, jaise abhi hai)
    GEMINI_API_KEY_2 ... _9   <- backup free keys
    GEMINI_API_KEY_BACKUP     <- backup ka doosra naam
    GEMINI_API_KEYS           <- ek hi line mein comma/space se alag ki hui list
"""
from __future__ import annotations

import hashlib
import os
from typing import Dict, List, Optional

_PRIMARY = "GEMINI_API_KEY"
_LIST_VARS = ("GEMINI_API_KEYS", "GEMINI_API_KEY_LIST", "GEMINI_BACKUP_KEYS")
_SPLIT = (",", ";", "\n", "\t", " ")


def _split_list(raw: str) -> List[str]:
    parts = [raw]
    for sep in _SPLIT:
        nxt: List[str] = []
        for part in parts:
            nxt.extend(part.split(sep))
        parts = nxt
    return [p.strip() for p in parts if p.strip()]


def load_keys(env: Optional[Dict[str, str]] = None) -> List[str]:
    """
    Env se saari free key kataar mein. Order maayne rakhta hai: pehle wahi key
    jo aaj tak chal rahi thi (`GEMINI_API_KEY`), taaki purana behaviour na badle.

    Duplicate hata dete hain (galti se ek hi key do jagah daal dena aam baat
    hai, aur usse "backup" ka bharam ho jaata — jabki quota wahi ek hi hai).
    """
    src = env if env is not None else os.environ
    raw: List[str] = [(src.get(_PRIMARY) or "").strip()]
    for i in range(2, 10):
        raw.append((src.get(f"{_PRIMARY}_{i}") or "").strip())
        raw.append((src.get(f"{_PRIMARY}{i}") or "").strip())
    raw.append((src.get(f"{_PRIMARY}_BACKUP") or "").strip())
    raw.append((src.get(f"{_PRIMARY}_FALLBACK") or "").strip())
    for name in _LIST_VARS:
        raw.extend(_split_list(src.get(name) or ""))

    out: List[str] = []
    for key in raw:
        if key and key not in out:
            out.append(key)
    return out


def fingerprint(key: str) -> str:
    """
    Key ka chhota, ULTA-na-ho-sakne-wala nishaan (sha256 ke pehle 8 hex).

    Kyun: "dono variable mein wahi ek key hai ya alag-alag?" — ye sawal warna
    sirf key dekh kar hi hal hota, jo kabhi bahar nahi jaani chahiye. Hash se
    key wapas nahi banayi ja sakti, par do key same hain ya alag, ye saaf pata
    chal jaata hai.
    """
    if not key:
        return ""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def describe(env: Optional[Dict[str, str]] = None) -> Dict:
    """
    Setup ki imaandaar report — BINA kisi key value ke.

    Lautata hai:
        names_present      -> kaunse env NAAM mein value mili (app inhe padhta hai)
        unique_keys        -> duplicate hatane ke baad kitni ASLI alag key bachi
        duplicates_dropped -> kitni entry duplicate thi (yahi "backup lag nahi
                              raha" ki sabse aam wajah hai)
        fingerprints       -> har unique key ka 8-hex nishaan (value nahi)
        note               -> ek line insaani samajh ke liye
    """
    src = env if env is not None else os.environ
    names: List[str] = []
    raw: List[str] = []

    def _take(name: str, value: str) -> None:
        value = (value or "").strip()
        if value:
            names.append(name)
            raw.append(value)

    _take(_PRIMARY, src.get(_PRIMARY) or "")
    for i in range(2, 10):
        _take(f"{_PRIMARY}_{i}", src.get(f"{_PRIMARY}_{i}") or "")
        _take(f"{_PRIMARY}{i}", src.get(f"{_PRIMARY}{i}") or "")
    _take(f"{_PRIMARY}_BACKUP", src.get(f"{_PRIMARY}_BACKUP") or "")
    _take(f"{_PRIMARY}_FALLBACK", src.get(f"{_PRIMARY}_FALLBACK") or "")
    for name in _LIST_VARS:
        for part in _split_list(src.get(name) or ""):
            _take(name, part)

    unique: List[str] = []
    for key in raw:
        if key not in unique:
            unique.append(key)

    dropped = len(raw) - len(unique)
    if not raw:
        note = ("Koi free key set nahi hai — GEMINI_API_KEY (aur chaaho to "
                "GEMINI_API_KEY_2) Railway → Variables mein daalo.")
    elif dropped and len(unique) == 1:
        note = ("Ek se zyada variable mein WAHI EK key hai, isliye backup nahi "
                "bana. Alag AI Studio project (ya alag Google account) ki alag "
                "key daalo — quota project par lagta hai, naam par nahi.")
    elif dropped:
        note = (f"{len(unique)} alag free key mili, {dropped} entry duplicate thi "
                f"(duplicate ginti mein nahi li gayi).")
    elif len(unique) == 1:
        note = ("Sirf ek free key hai. Backup ke liye GEMINI_API_KEY_2 mein alag "
                "project ki key daal sakte ho (₹0). Iske bina bhi app rukega "
                "nahi — offline reasoning jawab bana deta hai.")
    else:
        note = f"{len(unique)} alag free key kataar mein hain — backup taiyar hai."

    return {"names_present": names, "unique_keys": len(unique),
            "duplicates_dropped": dropped,
            "fingerprints": [fingerprint(k) for k in unique],
            "note": note}


class KeyPool:
    """
    Free key ki kataar + "abhi kaun chal rahi hai" ka hisaab.

    `advance()` tabhi True lautata hai jab sach mein ek AUR key maujood hai.
    Isliye ek hi key wale setup mein (aaj ka Railway) sab kuch waisa hi chalta
    hai jaisa pehle chalta tha — koi naya risk nahi.
    """

    def __init__(self, keys: Optional[List[str]] = None) -> None:
        self._keys: List[str] = [k for k in (keys if keys is not None
                                            else load_keys()) if k]
        self._index = 0
        self.switches = 0
        # kaun kis wajah se chhodi gayi — sirf LABEL aur wajah, key nahi
        self.retired: List[Dict[str, str]] = []

    # ── ginti ────────────────────────────────────────────────────────────────
    @property
    def count(self) -> int:
        return len(self._keys)

    @property
    def index(self) -> int:
        return self._index

    def has_key(self) -> bool:
        return bool(self._keys)

    def has_backup(self) -> bool:
        """Aage ek aur key bachi hai ya nahi (yahi asli sawal hai)."""
        return self._index + 1 < len(self._keys)

    def remaining(self) -> int:
        return max(0, len(self._keys) - self._index - 1)

    # ── naam (kabhi value nahi) ──────────────────────────────────────────────
    def label(self, index: Optional[int] = None) -> str:
        i = self._index if index is None else index
        if not self._keys:
            return "koi free key set nahi"
        return f"free key #{i + 1}"

    def previous_label(self) -> str:
        return self.label(max(0, self._index - 1))

    def labels(self) -> List[str]:
        return [self.label(i) for i in range(len(self._keys))]

    # ── asli value (sirf SDK ko dene ke liye) ────────────────────────────────
    def active(self) -> str:
        """
        Abhi ki key ki value. Ye SIRF `genai.configure()` ko jaati hai — isse
        log/notes/audit mein kabhi mat likho.
        """
        if not self._keys:
            return ""
        return self._keys[min(self._index, len(self._keys) - 1)]

    # ── shift ────────────────────────────────────────────────────────────────
    def advance(self, reason: str = "") -> bool:
        """
        Agli free key par jao. Aage koi key na ho to False — caller ko tab
        imaandaari se batana chahiye ki backup khatam ho gaya.
        """
        if not self.has_backup():
            return False
        self.retired.append({"key": self.label(), "reason": reason or "quota"})
        self._index += 1
        self.switches += 1
        return True

    def note(self) -> str:
        """Audit ke liye ek line — bina kisi key value ke."""
        if not self._keys:
            return "Koi free Gemini key set nahi hai."
        bits = [f"{self.count} free key available", f"abhi {self.label()} chal rahi hai"]
        if self.switches:
            bits.append(f"{self.switches} baar backup key par shift karna pada")
        for item in self.retired:
            bits.append(f"{item['key']} chhodi gayi ({item['reason']})")
        return ", ".join(bits)
