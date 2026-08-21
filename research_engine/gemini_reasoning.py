"""
GeminiReasoning — Spec Section 9 (Multi-Angle Reasoning)

Gemini = REASONING ENGINE. Knowledge base nahi.
Isliye har prompt mein evidence pack jaata hai aur model ko bola jaata hai ki
sirf diye gaye sources se cite kare.

Do zaroori cheezein ye module handle karta hai:
    1. CALL BUDGET — free tier ~20 calls/din. Budget khatam hone pe engine
       aage ki pass silently skip karta hai, crash nahi karta.
    2. HONESTY — Spec Section 9: "ek hi Gemini model ke alag passes ko
       'independent human experts' mat batana." Prompt mein yahi likha hai.
"""
from __future__ import annotations

import os
import time
from typing import Dict, List, Optional

from .citation import CITATION_INSTRUCTION
from .claim_labels import LABEL_RULE_PROMPT
from .explain_style import style_block
from .key_pool import KeyPool
from .model_errors import AUTH, DAILY_QUOTA, FailureLedger
from .model_errors import classify as classify_error
from .models import EvidencePack

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

# Ye disclaimer har analysis prompt mein jaata hai
_ROLE_HONESTY = (
    "NOTE: tum ek hi AI model ho jo alag-alag reasoning roles nibha raha hai. "
    "In roles ko 'independent human experts' ki tarah pesh mat karo. "
    "Evidence ki asli verification sources se hoti hai, roles se nahi."
)

# ── retry policy (2026-08-20 ki live failure ke baad) ────────────────────────
# Us run mein ek 429 ne TEEN passes ek saath uda diye: critic, hypothesis aur
# synthesis. Wajah ye thi ki `generate()` har exception ko nigal kar "" lauta
# deta tha — na retry, na doosra model. Jabki free tier ka quota PER MODEL hota
# hai, aur `/api/v1/chat/diag` par 25 usable model dikh rahe the. Yaani jawab
# maujood tha, system ne maanga hi nahi.
#
# DUSRI live failure (§7): usi 429 ko "random network error" maan kar 3 baar
# retry kiya gaya, jabki message mein saaf likha tha ki DIN ka quota khatam hai
# (quota_id: ...PerDay...). Ab error ka matlab `model_errors.py` batata hai:
#   * daily quota      -> usi model par dobara NAHI, model is run ke liye band
#   * per-minute limit -> thoda ruk kar dobara
#   * 404/naam galat   -> model permanently chhod do (process-wide memory)
#   * auth failure     -> poori reasoning band, aur koshish bekaar hai
#   * 5xx / network    -> retry
_BACKOFF_SECONDS = (1.5, 4.0)      # ek pass ke andar max ~6s rukte hain
_MAX_SLEEP_SECONDS = 6.0           # server 21s maange to bhi itna hi rukte hain
_MAX_MODELS = 4                    # pehla + teen fallback (quota per model hota hai)

# ── §8 backup FREE keys (2026-08-21 ki demand) ───────────────────────────────
# intel: "gimini ko call krte h to quta khatam ho jaata h ... iska quta khatam ho
# gya, ye kaam nhi kiya, iss wajah se jawab thoda week rah gya."
#
# Model rotation (upar) sirf tab bachaata hai jab quota PER MODEL khatam ho. Par
# free tier ki asli deewar `GenerateRequestsPerDayPerProject` hai — us halat mein
# us KEY ke saare model ek saath band ho jaate hain. Uska ek hi ₹0 ilaaj hai:
# doosri FREE key (alag AI Studio project) par shift kar jaana — `key_pool.py`.
#
# Do niyam pakke hain:
#   * key badalna RETRY NAHI hai — §14 ka hisaab isse alag ginta hai.
#   * key ki VALUE kabhi note/error/audit mein nahi jaati, sirf "free key #2".


def _classify(exc: Exception) -> str:
    """
    Legacy label — purane callers/tests ke liye. Asli faisla
    `model_errors.classify()` karta hai; ye sirf uska chhota naam hai.
    """
    return classify_error(exc).kind


class QuotaExhausted(RuntimeError):
    pass


class GeminiReasoning:
    def __init__(self, budget: int = 2, model_name: str = MODEL_NAME):
        self.budget = max(1, budget)
        self.model_name = model_name
        self.calls_used = 0
        self.errors: List[str] = []
        self._model = None
        # retry ka hisaab — ye audit section mein imaandaari se dikhta hai
        self.attempts = 0                    # asli HTTP attempts (retry ke saath)
        self.successes = 0                   # kitne pass sach mein jawab laaye
        self.notes: List[str] = []           # "critique: model X par safal (retry 2)"
        self.models_tried: List[str] = []
        self.switched_models = 0             # doosre model par kitni baar gaye
        self.same_model_retries = 0          # WAHI model, dobara (asli retry)
        # §7 — kaun kis wajah se gira, aur kaun is run mein band hai
        self.ledger = FailureLedger()
        self.blocked: Dict[str, str] = {}    # model -> kind (is run ke liye)
        self.stopped = False                 # auth failure: aage koshish bekaar
        # §14 — har pass ka apna record: naam, output aaya ya nahi, kitni HTTP
        # attempts lagi, kis model par chala. `calls_used` sirf "maanga gaya"
        # batata hai; ye list "mila ya nahi" batati hai. Purane audit mein
        # "3/3 reasoning pass" chhapta tha jabki teeno khaali laut sakte the.
        self.pass_log: List[Dict] = []
        # §8 — free key ki kataar. Ek hi key ho to `has_backup()` hamesha False
        # rehta hai, isliye purana behaviour bilkul waisa hi chalta hai.
        self.keys = KeyPool()
        self.key_switches = 0                # doosri FREE key par kitni baar gaye

    # ── model access (lazy) ──────────────────────────────────────────────────
    def model(self):
        if self._model is None:
            import google.generativeai as genai  # lazy — import sasta rahe
            from dotenv import load_dotenv

            from .gemini_model import configure, resolve

            load_dotenv()
            if not self.keys.has_key():
                # .env ab load hui hai — ho sakta hai key ab dikhe (constructor
                # ke waqt process env khaali tha).
                self.keys = KeyPool()
            configure(genai, self.keys.active())
            # Hard-coded naam ("gemini-flash-latest") kai keys par maujood nahi
            # hota aur Google InvalidArgument/NotFound bhej deta hai. Isliye
            # naam Google ki asli list se chunte hain. GEMINI_MODEL env set ho
            # aur valid ho to wahi use hota hai.
            if self.model_name == MODEL_NAME:
                self.model_name = resolve(genai)
            self._model = genai.GenerativeModel(self.model_name)
        return self._model

    # ── §8: agli FREE key par shift ──────────────────────────────────────────
    def _switch_key(self, tag: str, reason: str = "quota") -> bool:
        """
        Agli free key par jao. True tabhi jab sach mein ek aur key thi.

        Naye key par purani key ki poori memory bekaar hai: kaunsa model band
        tha, kaunsa naam 404 de raha tha, auth fail hua tha — ye sab key ke saath
        badalta hai. Isliye sab saaf karke naye sire se model resolve karte hain.
        """
        if not self.keys.has_backup():
            return False
        dead = self.keys.label()
        if not self.keys.advance(reason):
            return False
        self.key_switches += 1
        # is key ke faisle purani key ke the — bhula do
        self.blocked.clear()
        self.stopped = False
        self._model = None
        self.model_name = MODEL_NAME
        try:
            from .gemini_model import reset_for_new_key
            reset_for_new_key()
        except Exception:                      # noqa: BLE001
            pass
        try:
            import google.generativeai as genai

            from .gemini_model import configure, resolve

            configure(genai, self.keys.active())
            self.model_name = resolve(genai, force=True)
            self._model = genai.GenerativeModel(self.model_name)
        except Exception as exc:               # noqa: BLE001 — kabhi crash nahi
            self.errors.append(f"{tag}: nayi free key par model setup: "
                               f"{type(exc).__name__}: {exc}")
            self._model = None
        # NOTE: yahan sirf LABEL jaata hai, key ki value kabhi nahi.
        self.notes.append(f"{tag}: {dead} ki free limit khatam thi — "
                          f"{self.keys.label()} par shift kiya (ye retry nahi hai)")
        return True

    def _model_order(self) -> List[str]:
        """Pehla = abhi ka model, uske baad gemini_model ke fallbacks."""
        order = [self.model_name] if self.model_name else []
        try:
            import google.generativeai as genai

            from .gemini_model import candidates

            for name in candidates(genai):
                if name not in order:
                    order.append(name)
        except Exception:                       # noqa: BLE001 — offline/no key
            pass
        return order[:_MAX_MODELS] or [self.model_name or MODEL_NAME]

    def _usable_models(self) -> List[str]:
        """
        Order mein se wo model hataao jo is run mein pehle hi gir chuke hain.

        Yahi §7 ka asli fayda hai: pehle pass mein jis model ka DIN ka quota
        khatam mila, agle pass mein us par dobara jaana sirf waqt aur attempts
        barbaad karta tha (aur user ko lagta tha "system atak gaya").
        """
        out: List[str] = []
        for name in self._model_order():
            if name in self.blocked:
                continue
            try:
                from .gemini_model import is_dead
                if is_dead(name):
                    continue
            except Exception:                   # noqa: BLE001
                pass
            out.append(name)
        return out

    def _build(self, name: str):
        """Naye naam ka model object banao (aur usse hi aage kaam karo)."""
        import google.generativeai as genai

        model = genai.GenerativeModel(name)
        self.model_name = name
        self._model = model
        return model

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.calls_used)

    # ── §9/§25: user ko batane layak wajah (raw error NAHI) ──────────────────
    def failure_kind(self) -> str:
        return self.ledger.worst_kind()

    def failure_reason(self) -> str:
        """Ek Hinglish line — kyun reasoning poori nahi hui."""
        kind = self.failure_kind()
        if not kind:
            return ""
        from .model_errors import HUMAN
        return HUMAN.get(kind, "")

    def technical_details(self, limit: int = 5) -> List[str]:
        """Report ke sabse NEECHE dikhane ke liye — upar kabhi nahi (§9)."""
        return [f"{e['model']} / {e['label']}: {e['kind']} — {e['detail']}"
                for e in self.ledger.events[:limit]]

    def generate(self, prompt: str, label: str = "") -> str:
        """
        Ek logical Gemini call — par andar retry + model fallback ke saath.

        Ye sirf patli parat hai: asli kaam `_generate` karta hai, aur yahan us
        pass ka imaandaar record (`pass_log`) banta hai — naam, output aaya ya
        nahi, kitni asli HTTP attempts lagi, kis model par chala.

        Kyun zaroori (§14): pehle audit sirf `calls_used` chhapta tha, yaani
        "3/3 reasoning pass". Par ek pass ho kar bhi khaali laut sakta hai
        (429, safety block, khaali text). Us halat mein "3/3" padh kar lagta tha
        3 baar sochh-vichaar hua — jabki hua kuch nahi. Ab dono ginti alag
        dikhti hain: kitne maange gaye, aur kitne se sach mein output aaya.
        """
        tag = label or "gemini"
        attempts_before = self.attempts
        text = self._generate(prompt, label)
        # QuotaExhausted yahan tak pahunchta hi nahi (upar se raise hota hai) —
        # aur wo theek hai: budget khatam wala pass maanga hi nahi gaya tha,
        # isliye use "khaali laut aaya" ginna galat hota.
        self.pass_log.append({
            "label": tag,
            "ok": bool(text),
            "http_attempts": max(0, self.attempts - attempts_before),
            "model": self.model_name if text else "",
        })
        return text

    def _generate(self, prompt: str, label: str = "") -> str:
        """
        Asli call loop — do parat: bahar KEY, andar MODEL.

        Budget LOGICAL calls ka hai (pass ka), retry us budget ko nahi khaata:
        warna ek 429 phir se poora pass kha jaata. Budget khatam ho to
        QuotaExhausted raise hota hai (ye behaviour purana hi hai, orchestrator
        isi par depend karta hai).

        §7 ke baad: kitni koshish honi hai, ye error ka MATLAB decide karta hai
        (model_errors.classify), andha 3-retry loop nahi.

        §8 ke baad: agar is key par SAB model gir gaye (din ka quota / auth), to
        hum ek aur FREE key par shift karke poora model-cycle dobara chalate hain.
        Ek hi key wale setup mein `has_backup()` False hota hai, isliye kuch nahi
        badalta.
        """
        if self.remaining <= 0:
            raise QuotaExhausted(f"call budget ({self.budget}) khatam — '{label}' skip hua")
        self.calls_used += 1
        tag = label or "gemini"

        if self.stopped:
            # auth fail ho chuka hai — dobara maangna sirf waqt kharab karna hai
            self.errors.append(f"{tag} skip: API key/permission failure ke baad "
                               f"aur koshish nahi ki gayi")
            return ""

        # ek pass ke andar zyada se zyada itni key try hongi (kataar ki lambai)
        for _ in range(max(1, self.keys.count)):
            text, key_level = self._one_key_cycle(prompt, tag)
            if text:
                return text
            if not key_level:
                # dikkat key ki nahi thi (safety block, khaali jawab, setup) —
                # nayi key bhi wahi jawab degi, isliye key barbaad mat karo
                return ""
            if not self._switch_key(tag, "free limit khatam"):
                if self.keys.count > 1:
                    self.notes.append(
                        f"{tag}: saari {self.keys.count} free keys ki limit "
                        f"khatam ho gayi — ab engine ka apna offline reasoning "
                        f"chalega")
                return ""
        return ""

    def _one_key_cycle(self, prompt: str, tag: str):
        """
        EK key par poora model-cycle. Lautata hai `(text, key_level_failure)`.

        `key_level_failure=True` ka matlab: jo gira wo MODEL ki galti nahi, is
        KEY ki hadd thi (din ka quota / auth / is key par koi model bacha nahi).
        Sirf us halat mein doosri key try karna samajhdaari hai.
        """
        key_level = False
        first_model = self.model_name
        try:
            self.model()                        # lazy resolve, taaki naam asli ho
        except Exception as exc:                # noqa: BLE001
            self.errors.append(f"{tag} failed: model setup: "
                               f"{type(exc).__name__}: {exc}")
            return "", False

        order = self._usable_models()
        if not order:
            self.errors.append(f"{tag} skip: is run mein koi model bacha hi nahi "
                               f"(band: {', '.join(sorted(self.blocked)) or '-'})")
            # is key par kuch nahi bacha — doosri key par sab model phir zinda
            # ho sakte hain (quota per project hota hai)
            return "", bool(self.blocked)

        for model_index, name in enumerate(order):
            if name not in self.models_tried:
                self.models_tried.append(name)
            if name != self.model_name:
                try:
                    self._build(name)
                except Exception as exc:        # noqa: BLE001
                    self.errors.append(f"{tag}: model '{name}' banaya nahi ja saka: "
                                       f"{type(exc).__name__}: {exc}")
                    continue
            if model_index:
                # §14 — switch YAHAN gina jaata hai: jab hum sach mein agle model
                # par aa gaye aur uspar attempt karne wale hain. Pehle ye sirf
                # SAFAL hone par ginta tha, isliye "dono model fail" wale run
                # mein switch 0 dikhta tha — jabki switch hua tha. Aur ye ginti
                # `same_model_retries` se bilkul alag hai: model badalna retry
                # nahi hai.
                self.switched_models += 1
            for attempt in range(len(_BACKOFF_SECONDS) + 1):
                self.attempts += 1
                try:
                    # Bandhi hui waqt-seema ke saath. Latki hui call ab TRANSIENT
                    # error ban kar wahi purana retry/backoff chalati hai — poori
                    # HTTP request ko ghanton rok kar nahi rakhti (isi wajah se
                    # website par aakhir mein "server se baat nahi ho paayi"
                    # aata tha).
                    from .gemini_model import generate as _generate
                    response = _generate(self._model, prompt)
                    text = (getattr(response, "text", "") or "").strip()
                    if not text:
                        # khaali jawab bhi failure hai — chup-chaap "" lautana
                        # hi purana bug tha
                        raise RuntimeError("model ne khaali response diya")
                    self.successes += 1
                    if name != first_model:
                        self.notes.append(
                            f"{tag}: '{first_model}' par nahi chala, "
                            f"'{name}' par chala")
                    elif attempt:
                        self.notes.append(f"{tag}: {attempt + 1} koshish ke baad chala")
                    return text, False
                except Exception as exc:        # noqa: BLE001
                    v = classify_error(exc)
                    self.ledger.add(name, tag, v, attempt=attempt + 1)
                    self.errors.append(
                        f"{tag} failed (model={name}, try={attempt + 1}, "
                        f"{v.kind}): {type(exc).__name__}: {exc}")

                    if v.stop_all:              # auth — is key par sab band
                        self.stopped = True
                        self.notes.append(f"{tag}: {v.human} — aage koshish rok di")
                        # key hi galat/band hai: doosri free key kaam kar sakti hai
                        return "", True
                    if v.permanent:
                        try:
                            from .gemini_model import mark_dead
                            mark_dead(name, v.kind)
                        except Exception:       # noqa: BLE001
                            pass
                    if v.disable_model:
                        self.blocked[name] = v.kind
                        # din ka quota is KEY/PROJECT ka hai — isliye ye key-level
                        # ishaara hai (doosri key par wahi model chal sakta hai)
                        if v.kind == DAILY_QUOTA:
                            key_level = True
                        self.notes.append(
                            f"{tag}: '{name}' {v.human} — is run mein isse "
                            f"dobara nahi poochha jaayega")
                        break                   # seedha agla model
                    if v.retry_same_model and attempt < len(_BACKOFF_SECONDS):
                        wait = v.retry_after or _BACKOFF_SECONDS[attempt]
                        if v.retry_after and v.retry_after > _MAX_SLEEP_SECONDS:
                            # server 21s maang raha hai — itna rukna user ke liye
                            # atak jaana hai; agle model par jaana behtar hai
                            self.notes.append(
                                f"{tag}: '{name}' ne {v.retry_after:.0f}s wait "
                                f"maanga — itna rukne se behtar agla model")
                            break
                        time.sleep(min(wait, _MAX_SLEEP_SECONDS))
                        # §14 — ASLI retry yahi hai: wahi model, dobara. Isse
                        # alag se ginna zaroori hai, warna model fallback bhi
                        # "retry" ban kar hisaab jhootha kar deta hai.
                        self.same_model_retries += 1
                        continue
                    break                       # is model par bas — agla model
        return "", key_level

    # ── §14: pass-level sach (maanga vs mila) ────────────────────────────────
    def passes_with_output(self) -> int:
        return len([p for p in self.pass_log if p.get("ok")])

    def empty_passes(self) -> List[str]:
        """Jo pass chale par khaali laute — naam ke saath, chhupaye bina."""
        return [str(p.get("label") or "?") for p in self.pass_log if not p.get("ok")]

    def usage_note(self) -> str:
        """Audit ke liye ek line — jitna hua utna, bina saja-sanwaar ke."""
        got = self.passes_with_output()
        asked = len(self.pass_log)
        bits = [f"{self.calls_used}/{self.budget} reasoning pass maange gaye"]
        if asked:
            # Yahi wo line hai jo pehle jhooth bolti thi: sirf "3/3 pass" likh
            # kar output ka koi zikr nahi hota tha.
            bits.append(f"inmein se {got}/{asked} se sach mein output aaya")
        empty = self.empty_passes()
        if empty:
            bits.append("khaali laute: " + ", ".join(empty[:4]))
        if self.attempts:
            bits.append(f"{self.attempts} actual API attempts")
        else:
            bits.append("0 actual API attempts (ek bhi network call nahi hui)")
        if self.same_model_retries:
            bits.append(f"{self.same_model_retries} same-model retry")
        if self.switched_models:
            # Ye jaan-boojh kar "retry" nahi kehta: doosre model par jaana retry
            # nahi hai, aur pehle audit dono ko ek hi number mein mila deta tha.
            bits.append(f"{self.switched_models} baar doosre model par shift karna pada")
        if self.key_switches:
            # §8 — key badalna bhi "retry" NAHI hai. Aur yahan sirf ginti aur
            # label jaata hai, key ki value kabhi nahi.
            bits.append(f"{self.key_switches} baar backup free key par shift karna "
                        f"pada (abhi {self.keys.label()})")
        if self.errors:
            bits.append(f"{len(self.errors)} error aaye")
        if self.blocked:
            bits.append("band model: " + ", ".join(
                f"{n} ({k})" for n, k in sorted(self.blocked.items())))
        return ", ".join(bits)

    def api_accounting(self) -> Dict:
        """
        §14 — honest API accounting. Har number ka ek hi matlab, aur do cheezein
        kabhi mila kar nahi ginte: WAHI model par dobara koshish (retry) aur
        DOOSRE model par jaana (fallback).

        Purana formula `retries = attempts - calls_used` tha, aur wahi bug tha:
        model A ek baar gira, model B par jawab mila to attempts=2, calls=1, aur
        report likh deti thi "1 retry" — jabki retry ek bhi nahi hua, model badla
        tha. Ab teen ginti alag hain:
          * `same_model_retries` — wahi model, dobara (asli retry)
          * `model_switches`     — agle model par kitni baar gaye
          * `actual_http_attempts` = pehli koshishein + same_model_retries

        Aur teen ginti "kaam kitna hua" ke liye alag hain, kyunki inka matlab
        alag hai aur pehle ye sab "calls" ke naam par ek number ban jaati thi:
          * `logical_reasoning_calls` — kitne pass MAANGE gaye
          * `passes_with_output`      — kitne pass se sach mein text aaya
          * `actual_http_attempts`    — network par kitni baar sach mein gaye
        `counted_by` isliye hai ki user ko pata rahe ye ginti engine ki apni hai,
        Google ke billing dashboard se nahi aayi.
        """
        asked = len(self.pass_log)
        got = self.passes_with_output()
        failed_http = max(0, self.attempts - self.successes)
        return {
            "logical_reasoning_calls": self.calls_used,
            "budget": self.budget,
            "passes_requested": asked,
            "passes_with_output": got,
            "passes_empty": max(0, asked - got),
            "empty_output_passes": self.empty_passes(),
            "pass_log": [dict(p) for p in self.pass_log],
            "actual_http_attempts": self.attempts,
            "successful_calls": self.successes,
            "failed_http_attempts": failed_http,
            # purana naam — bahar ke callers na toote (wahi number, naya naam
            # `failed_http_attempts` hai)
            "failed_attempts": failed_http,
            "same_model_retries": self.same_model_retries,
            # `retries` ab SIRF asli retry hai (pehle isme model switch bhi
            # ghusa hua tha)
            "retries": self.same_model_retries,
            "models_tried": list(self.models_tried),
            "model_switches": self.switched_models,
            # §8 — free key ka hisaab. `key_switches` ko kabhi "retry" mat
            # padho: nayi key par jaana pehli koshish hoti hai, dobari nahi.
            # Isliye identity ab ye hai:
            #   actual_http_attempts
            #     == (1 + key_switches) + same_model_retries + model_switches
            # Ek hi key wale setup mein key_switches = 0, yaani purana formula
            # jaisa ka waisa.
            "keys_available": self.keys.count,
            "key_switches": self.key_switches,
            "active_key": self.keys.label(),      # sirf label — value kabhi nahi
            "keys_note": self.keys.note(),
            "blocked_models": dict(self.blocked),
            "failure_kinds": self.ledger.kinds(),
            "failure_summary": self.ledger.summary(),
            "stopped_early": self.stopped,
            "no_api_calls": self.attempts == 0,
            "counted_by": "engine ki apni ginti (Google billing dashboard se nahi)",
        }

    # ── PASS 1/2/3 + evidence audit (Spec Section 9) ─────────────────────────
    def prompt_analysis(self, question: str, pack: EvidencePack, plan: Dict) -> str:
        fields = ", ".join(plan.get("relevant_fields", [])) or "General"
        subs = "\n".join(f"  - {s}" for s in plan.get("sub_questions", [])[:5])
        # Bhasha + samjhane ka tarika yahan bhi zaroori hai, sirf synthesis mein
        # nahi: jab quota synthesis tak nahi pahunchti (2 mein se 1 call, ya
        # 429), tab YAHI analysis seedha final answer ban jaata hai
        # (orchestrator: `passes["final"] or passes["analysis"]`). Pehle us
        # halat mein user ko bilkul kaccha, jargon-bhara text milta tha.
        style = style_block(question, ["Factual Findings"])
        # Explicit requests (math model, chain, hypothesis count) plan ke andar
        # aate hain — planner ne `requests` daala hoga. Na ho to ye khaali string
        # ban jaata hai, isliye purane callers bhi chalte rehte hain.
        from .requested import prompt_block

        extras = prompt_block(plan.get("requests") if isinstance(plan, dict) else None)
        # PATENT RULE sirf tab jaata hai jab pack mein sach mein patent ho —
        # warna har normal sawaal ke prompt mein bekaar tokens jaate.
        patent_rules = ""
        try:
            if pack.patent_sources():
                from .patents import PATENT_RULE_PROMPT
                patent_rules = "\n" + PATENT_RULE_PROMPT
        except Exception:          # pragma: no cover - purane pack objects
            patent_rules = ""
        return f"""Tum ek Research Analyst ho. {_ROLE_HONESTY}

SAWAL: {question}

RELEVANT FIELDS: {fields}

SUB-QUESTIONS jinka jawab chahiye:
{subs}

RETRIEVED SOURCES (sirf inhi ka istemal karo):
{pack.to_prompt_block()}

{CITATION_INSTRUCTION}

{LABEL_RULE_PROMPT}
{patent_rules}

{style}

Ab ye passes karo:

PASS 1 — FACTUAL: sirf wo facts jo in sources se supported hain. Har fact ke saath
  source ID, aur label upar diye gaye LABEL RULE ke hisaab se:
  jis source ka "Read: full_text" hai usse verify hui baat par [ESTABLISHED],
  aur sirf abstract/snippet/metadata wali baat par [SOURCE-REPORTED].
PASS 2 — CONTEXT: background, mechanism, relationships. Jahan source nahi hai
  wahan [INFERENCE] + [NO-SOURCE] likho.
PASS 3 — CROSS-DISCIPLINARY: {fields} ko aapas mein connect karo. Har connection
  evidence ya clearly-labelled inference par based ho.
PASS 4 — EVIDENCE AUDIT: har major claim ko label karo:
  [ESTABLISHED] [SOURCE-REPORTED] [MIXED EVIDENCE] [INFERENCE] [HYPOTHESIS]
  [SPECULATION] [UNKNOWN]
{extras}

Output format:
## Factual Findings
## Context & Mechanisms
## Cross-Disciplinary Connections
## Evidence Audit
## Source Relevance Check
   (Agar diye gaye sources sawal ke liye relevant NAHI hain, to yahan saaf likho.)

Ab analysis do:"""

    # ── fallback: koi source hi nahi mila ────────────────────────────────────
    def prompt_no_sources(self, question: str, plan: Dict) -> str:
        return f"""Tum ek research assistant ho. Is sawal ke liye system ko koi
relevant source NAHI mila (na document, na web, na academic database).

SAWAL: {question}

{style_block(question)}

Rules:
1. Shuru mein hi saaf likho: "Ye jawab retrieved sources se nahi, model ki
   general knowledge se hai."
2. Har claim ko [INFERENCE] ya [UNKNOWN] label karo — [ESTABLISHED] mat likho,
   kyunki verify karne ke liye koi source nahi hai.
3. Koi URL ya citation invent MAT karo.
4. Aakhir mein batao ki is sawal ka jawab verify karne ke liye kaun se
   sources/data chahiye honge.

Jawab do:"""
