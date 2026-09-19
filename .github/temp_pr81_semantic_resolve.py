"""Temporary deterministic resolver for PR81 generation-window integration.

Runs only inside the disposable integration workflow while commit 8febb75 is in
CHERRY_PICK_HEAD. It preserves the current stack's durable quota, shared model
cooldown and lossless handoff semantics while adding the measured cooperative
generation-window/accounting repair. No provider calls are made here.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess


def stage(number: int, path: str) -> str:
    return subprocess.check_output(["git", "show", f":{number}:{path}"], text=True)


def write_checked(path: str, text: str) -> None:
    if path.endswith(".py"):
        compile(text, path, "exec")
    Path(path).write_text(text, encoding="utf-8")


def resolve_company_worker() -> None:
    path = "research_engine/company_worker.py"
    text = stage(3, path)
    old = '        context = RunContext(RuntimeStore(wire["path"]), wire["project"], wire["run"]) if wire else None\n'
    new = (
        '        context = RunContext(RuntimeStore(wire["path"]), wire["project"], wire["run"],\n'
        '                             deadline=wire.get("deadline")) if wire else None\n'
    )
    assert text.count(old) == 1
    write_checked(path, text.replace(old, new, 1))


def resolve_research_company() -> None:
    path = "research_engine/research_company.py"
    text = stage(2, path)
    old = '    try:\n        payload = dict(payload)\n'
    new = (
        '    try:\n'
        '        generation_deadline = time.time() + max(0.0, timeout - min(10.0, timeout / 10))\n'
        '        payload = dict(payload, generation_deadline=generation_deadline)\n'
    )
    assert text.count(old) == 1
    text = text.replace(old, new, 1)
    old = '            payload["runtime_context"] = dict(wire, deadline=deadline)\n'
    new = old + '            payload["generation_deadline"] = min(payload["generation_deadline"], deadline)\n'
    assert text.count(old) == 1
    write_checked(path, text.replace(old, new, 1))


def resolve_runtime() -> None:
    path = "utils/research_runtime.py"
    text = stage(2, path)
    anchor = (
        'class ResearchCancelled(RuntimeBlocked):\n'
        '    pass\n\n\n'
        'class ModelCooldownActive(RuntimeBlocked):\n'
    )
    generation = '''class ResearchCancelled(RuntimeBlocked):
    pass


class GenerationDeadline(RuntimeBlocked):
    """The cooperative worker window ended before another request dispatch."""


_GENERATION_DEADLINE = contextvars.ContextVar("generation_deadline", default=None)


@contextlib.contextmanager
def generation_window(seconds):
    """Share one elapsed-time budget across discovery, retries and fallbacks.

    This cooperative limit complements the parent's hard process timeout; a
    non-cooperating SDK/process still has UNKNOWN accounting if it is killed.
    Nested scopes may shorten the window, never extend it.
    """
    deadline = time.monotonic() + max(0.0, float(seconds))
    outer = _GENERATION_DEADLINE.get()
    token = _GENERATION_DEADLINE.set(min(deadline, outer) if outer is not None else deadline)
    try:
        yield
    finally:
        _GENERATION_DEADLINE.reset(token)


def generation_window_active():
    return _GENERATION_DEADLINE.get() is not None


def bounded_request_timeout(seconds):
    deadline = _GENERATION_DEADLINE.get()
    if deadline is None:
        return seconds
    remaining = deadline - time.monotonic()
    if remaining <= 0.1:
        raise GenerationDeadline("worker generation window exhausted")
    return min(float(seconds), remaining)


def bounded_http_timeout(connect, read):
    """Share remaining time between connection setup and a provider read."""
    if not generation_window_active():
        return (connect, read)
    remaining = bounded_request_timeout(connect + read)
    connection = min(float(connect), remaining / 4)
    return (connection, min(float(read), remaining - connection))


class ModelCooldownActive(RuntimeBlocked):
'''
    assert text.count(anchor) == 1
    text = text.replace(anchor, generation, 1)

    old = '''def wait_for_model_retry(delay):
    """Cancellable wait within the existing run/worker deadline, no reservation."""
    if current() is None or not math.isfinite(delay) or delay < 0:
        return False
    remaining = remaining_seconds()
'''
    new = '''def wait_for_model_retry(delay):
    """Cancellable wait within both run and cooperative generation deadlines."""
    if current() is None or not math.isfinite(delay) or delay < 0:
        return False
    if generation_window_active():
        try:
            bounded = bounded_request_timeout(delay)
        except GenerationDeadline:
            return False
        if bounded + 1e-9 < delay:
            return False
    remaining = remaining_seconds()
'''
    assert text.count(old) == 1
    write_checked(path, text.replace(old, new, 1))


def resolve_gemini_reasoning() -> None:
    path = "research_engine/gemini_reasoning.py"
    text = Path(path).read_text(encoding="utf-8")
    pattern = re.compile(r'^<<<<<<< .*?\n(.*?)^=======\n(.*?)^>>>>>>> .*?\n', re.M | re.S)

    dispatch = '''                from utils.research_runtime import (
                    current, model_cooldown_scopes, ModelCooldownActive,
                    reserve_request, remember_model_failure, remaining_seconds,
                )
                left = remaining_seconds()
                effective_timeout = min(request_timeout, left) if left is not None else request_timeout
                attempt_timeout = bounded_request_timeout(effective_timeout)
                scopes = model_cooldown_scopes("gemini", self.keys.active(), name) if current() else ()
                try:
                    if scopes:
                        reserve_request("gemini", request_prompt, 6000, cooldown_scopes=scopes)
                    else:
                        reserve_request("gemini", request_prompt, 6000)
                except ModelCooldownActive as cooldown:
                    # A sibling already observed this failure. No HTTP attempt,
                    # reservation or success is invented for the skipped call.
                    v = ErrorVerdict(kind=cooldown.kind, detail="shared_run_cooldown")
                    self.ledger.add(name, tag, v, attempt=0)
                    self.ledger.events[-1]["origin"] = "shared_run_cooldown"
                    self.notes.append(f"{tag}: shared run cooldown ({v.kind}); model request skipped")
                    if v.kind == AUTH:
                        return "", True
                    if v.kind == DAILY_QUOTA:
                        key_level = True
                    if v.kind == RATE_LIMIT:
                        recovery_times[name] = time.time() + cooldown.retry_after
                    else:
                        recovery_times.pop(name, None)
                    break
                counts_before_dispatch = (self.attempts, self.same_model_retries,
                                          self.switched_models, self.prompt_compactions,
                                          self.timeout_extensions)
                history_before_dispatch = len(history)
                if name in history:
                    self.same_model_retries += 1
                if history and name != history[-1]:
                    self.switched_models += 1
                if compacted_for_model and not compaction_counted:
                    self.prompt_compactions += 1
                    compaction_counted = True
                if timeout_extended and not extension_counted:
                    self.timeout_extensions += 1
                    extension_counted = True
                history.append(name)
'''

    seen = 0

    def choose(match: re.Match[str]) -> str:
        nonlocal seen
        seen += 1
        ours, incoming = match.group(1), match.group(2)
        if "ModelCooldownActive" in ours and "attempt_timeout" in incoming:
            return dispatch
        if "self.prompt_compactions += 1" in ours:
            return incoming
        if "self.timeout_extensions += 1" in ours:
            return incoming
        if "time.sleep" in ours and "bounded_request_timeout" in incoming:
            return incoming
        raise AssertionError(f"unexpected gemini conflict #{seen}")

    text = pattern.sub(choose, text)
    assert seen == 4

    old = (
        '                    from .gemini_model import generate as _generate\n'
        '                    from utils.research_runtime import remaining_seconds\n'
        '                    left = remaining_seconds()\n'
        '                    if left is not None:\n'
        '                        request_timeout = min(request_timeout, left)\n'
        '                    response = _generate(\n'
    )
    new = (
        '                    from .gemini_model import generate as _generate\n'
        '                    response = _generate(\n'
    )
    assert text.count(old) == 1
    text = text.replace(old, new, 1)

    old = (
        '                    self.prompt_attempt_log.pop()\n'
        '                    raise\n'
        '                except Exception as exc:'
    )
    new = (
        '                    del history[history_before_dispatch:]\n'
        '                    self.prompt_attempt_log.pop()\n'
        '                    raise\n'
        '                except Exception as exc:'
    )
    assert text.count(old) == 1
    text = text.replace(old, new, 1)
    assert "<<<<<<<" not in text and ">>>>>>>" not in text and "\n=======\n" not in text
    write_checked(path, text)


def main() -> None:
    resolve_company_worker()
    resolve_research_company()
    resolve_runtime()
    resolve_gemini_reasoning()
    print("semantic conflict resolution: PASS")


if __name__ == "__main__":
    main()
