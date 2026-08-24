"""Leakage-safe exam-pattern analysis and probabilistic forecasting.

This module does **not** read an examiner's mind and does not promise exact
questions.  It turns a dated, source-traceable collection of public/user-
provided past papers plus an official syllabus into:

* study-priority scores (explicitly not probabilities);
* observable paper-selection patterns;
* temporal walk-forward backtests that never train on a held-out/future paper;
* empirical forecast frequencies only when the history is large enough;
* separately labelled, falsifiable app-original exam hypotheses; and
* a durable, project-isolated analysis ledger.

No model, network request, paid service or arbitrary code execution is used.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Mapping, Sequence

from .network_safety import UnsafeURL, validate_public_http_url
from utils.process_lock import ExclusiveProcessFileLock


SCHEMA_VERSION = 1
_MIN_CALIBRATION_SPLITS = 6
_MIN_CALIBRATION_PAIRS = 60
_MIN_BIN_SAMPLES = 5
_QUESTION_TYPES = {
    "mcq", "numeric", "statement", "matching", "short_answer",
    "long_answer", "other",
}
_COGNITIVE_LEVELS = {
    "recall", "understanding", "application", "analysis", "mixed", "unknown",
}
_SPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[^\w\u0900-\u097f]+", re.UNICODE)


class ExamDataError(ValueError):
    """Input cannot be analysed without guessing or accepting leakage."""


def _clean(value: object, limit: int = 500) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()[: max(0, int(limit))]


def _identifier(value: object, field: str) -> str:
    clean = _clean(value, 100)
    if not clean or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", clean):
        raise ExamDataError(f"{field} must be a stable 1-100 character identifier")
    return clean


def _as_date(value: object, field: str, *, required: bool = True) -> date | None:
    if value in (None, ""):
        if required:
            raise ExamDataError(f"{field} is required")
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ExamDataError(f"{field} must be an ISO date (YYYY-MM-DD)") from None


def _normal_question(text: object) -> str:
    return _TOKEN_RE.sub(" ", _clean(text, 4000).casefold()).strip()


def _public_url(value: object) -> tuple[str, list[str]]:
    raw = _clean(value, 2048)
    if not raw:
        return "", ["SOURCE_URL_NOT_SUPPLIED"]
    try:
        return validate_public_http_url(raw, resolve_dns=False), []
    except UnsafeURL:
        return "", ["UNSAFE_SOURCE_URL_REMOVED"]


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


@dataclass(frozen=True)
class SyllabusTopic:
    topic_id: str
    subject: str
    chapter: str
    topic: str
    official_weight: float = 1.0


@dataclass(frozen=True)
class ExamQuestion:
    question_id: str
    text: str
    topic_ids: tuple[str, ...]
    marks: float
    question_type: str
    cognitive_level: str


@dataclass(frozen=True)
class ExamPaper:
    paper_id: str
    held_on: date
    available_from: date
    availability_assumed: bool
    source_id: str
    source_url: str
    source_warnings: tuple[str, ...]
    questions: tuple[ExamQuestion, ...]


def _topics(rows: Sequence[Mapping[str, object]]) -> list[SyllabusTopic]:
    if not rows:
        raise ExamDataError("official syllabus topics are required")
    if len(rows) > 500:
        raise ExamDataError("syllabus topic limit exceeded (500)")
    out: list[SyllabusTopic] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ExamDataError(f"syllabus[{index}] must be an object")
        topic_id = _identifier(row.get("topic_id"), f"syllabus[{index}].topic_id")
        if topic_id in seen:
            raise ExamDataError(f"duplicate syllabus topic_id: {topic_id}")
        seen.add(topic_id)
        subject = _clean(row.get("subject"), 120)
        chapter = _clean(row.get("chapter"), 180)
        topic = _clean(row.get("topic"), 220)
        if not subject or not chapter or not topic:
            raise ExamDataError(f"syllabus[{index}] needs subject, chapter and topic")
        try:
            weight = float(row.get("official_weight", 1.0) or 1.0)
        except (TypeError, ValueError):
            raise ExamDataError(f"syllabus[{index}].official_weight must be numeric") from None
        if not (0.1 <= weight <= 20.0):
            raise ExamDataError(f"syllabus[{index}].official_weight must be 0.1-20")
        out.append(SyllabusTopic(topic_id, subject, chapter, topic, weight))
    return out


def _questions(
    rows: Sequence[Mapping[str, object]],
    *,
    paper_id: str,
    topic_ids: set[str],
) -> tuple[ExamQuestion, ...]:
    if not rows:
        raise ExamDataError(f"paper {paper_id} has no questions")
    if len(rows) > 500:
        raise ExamDataError(f"paper {paper_id} exceeds 500 questions")
    out: list[ExamQuestion] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ExamDataError(f"paper {paper_id} question {index} must be an object")
        question_id = _identifier(
            row.get("question_id"), f"paper {paper_id} question_id"
        )
        if question_id in seen:
            raise ExamDataError(f"duplicate question_id in {paper_id}: {question_id}")
        seen.add(question_id)
        text = _clean(row.get("text"), 4000)
        if len(text) < 3:
            raise ExamDataError(f"question {question_id} text is missing/too short")
        raw_topics = list(row.get("topic_ids") or [])
        mapped: list[str] = []
        for raw in raw_topics[:12]:
            topic_id = _identifier(raw, f"question {question_id}.topic_ids")
            if topic_id not in topic_ids:
                raise ExamDataError(
                    f"question {question_id} maps to unknown syllabus topic {topic_id}"
                )
            if topic_id not in mapped:
                mapped.append(topic_id)
        if not mapped:
            raise ExamDataError(f"question {question_id} has no syllabus topic mapping")
        try:
            marks = float(row.get("marks", 1.0) or 1.0)
        except (TypeError, ValueError):
            raise ExamDataError(f"question {question_id}.marks must be numeric") from None
        if not (0 < marks <= 1000):
            raise ExamDataError(f"question {question_id}.marks must be >0 and <=1000")
        question_type = _clean(row.get("question_type") or "other", 40).lower()
        if question_type not in _QUESTION_TYPES:
            question_type = "other"
        cognitive = _clean(row.get("cognitive_level") or "unknown", 40).lower()
        if cognitive not in _COGNITIVE_LEVELS:
            cognitive = "unknown"
        out.append(ExamQuestion(
            question_id, text, tuple(mapped), marks, question_type, cognitive,
        ))
    return tuple(out)


def _papers(
    rows: Sequence[Mapping[str, object]],
    *,
    topic_ids: set[str],
) -> list[ExamPaper]:
    if not rows:
        raise ExamDataError("at least one dated past paper is required")
    if len(rows) > 60:
        raise ExamDataError("past paper limit exceeded (60)")
    out: list[ExamPaper] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ExamDataError(f"papers[{index}] must be an object")
        paper_id = _identifier(row.get("paper_id"), f"papers[{index}].paper_id")
        if paper_id in seen:
            raise ExamDataError(f"duplicate paper_id: {paper_id}")
        seen.add(paper_id)
        held = _as_date(row.get("held_on"), f"paper {paper_id}.held_on")
        raw_available = row.get("available_from")
        available = _as_date(
            raw_available, f"paper {paper_id}.available_from", required=False
        )
        assumed = available is None
        available = available or held
        if available < held:
            raise ExamDataError(
                f"paper {paper_id}.available_from is earlier than held_on; "
                "possible leaked/pre-release paper blocked"
            )
        source_id = _clean(row.get("source_id"), 160)
        source_url, source_warnings = _public_url(row.get("source_url"))
        questions = _questions(
            list(row.get("questions") or []), paper_id=paper_id, topic_ids=topic_ids
        )
        out.append(ExamPaper(
            paper_id=paper_id,
            held_on=held,
            available_from=available,
            availability_assumed=assumed,
            source_id=source_id,
            source_url=source_url,
            source_warnings=tuple(source_warnings),
            questions=questions,
        ))
    return sorted(out, key=lambda row: (row.held_on, row.paper_id))


def _paper_topic_marks(paper: ExamPaper) -> dict[str, float]:
    marks: dict[str, float] = defaultdict(float)
    for question in paper.questions:
        share = question.marks / max(1, len(question.topic_ids))
        for topic_id in question.topic_ids:
            marks[topic_id] += share
    return dict(marks)


def _score_topics(
    syllabus: Sequence[SyllabusTopic], papers: Sequence[ExamPaper]
) -> list[dict]:
    if not papers:
        return []
    topic_marks_by_paper = [_paper_topic_marks(paper) for paper in papers]
    total_marks = sum(sum(row.values()) for row in topic_marks_by_paper) or 1.0
    latest_index = len(papers) - 1
    recency_weights = [0.82 ** (latest_index - index) for index in range(len(papers))]
    recency_total = sum(recency_weights) or 1.0
    max_weight = max(topic.official_weight for topic in syllabus) or 1.0

    raw: list[dict] = []
    for topic in syllabus:
        presence = [topic.topic_id in marks for marks in topic_marks_by_paper]
        occurrence_count = sum(1 for present in presence if present)
        base_rate = occurrence_count / len(papers)
        recency_rate = sum(
            weight for weight, present in zip(recency_weights, presence) if present
        ) / recency_total
        topic_marks = sum(marks.get(topic.topic_id, 0.0) for marks in topic_marks_by_paper)
        marks_share = topic_marks / total_marks
        seen_indices = [index for index, present in enumerate(presence) if present]
        gap_papers = latest_index - max(seen_indices) if seen_indices else len(papers)
        gap_signal = min(1.0, gap_papers / max(1, len(papers) - 1)) * base_rate
        syllabus_signal = topic.official_weight / max_weight
        raw.append({
            "topic": topic,
            "occurrence_count": occurrence_count,
            "base_rate": base_rate,
            "recency_rate": recency_rate,
            "marks_share": marks_share,
            "gap_papers": gap_papers,
            "gap_signal": gap_signal,
            "syllabus_signal": syllabus_signal,
        })

    max_marks_share = max((row["marks_share"] for row in raw), default=1.0) or 1.0
    results: list[dict] = []
    for row in raw:
        marks_signal = row["marks_share"] / max_marks_share
        score = 100.0 * (
            0.38 * row["base_rate"]
            + 0.24 * row["recency_rate"]
            + 0.16 * marks_signal
            + 0.12 * row["gap_signal"]
            + 0.10 * row["syllabus_signal"]
        )
        reasons: list[str] = []
        if row["base_rate"] >= 0.60:
            reasons.append("HIGH_HISTORICAL_COVERAGE")
        if row["recency_rate"] > row["base_rate"] + 0.12:
            reasons.append("RECENT_UPTREND")
        if row["gap_papers"] >= 2 and row["base_rate"] >= 0.30:
            reasons.append("LONG_OMISSION_AFTER_REPEAT")
        if marks_signal >= 0.75:
            reasons.append("HIGH_RELATIVE_MARK_SHARE")
        if row["occurrence_count"] == 0:
            reasons.append("OFFICIAL_SYLLABUS_BUT_UNSEEN_IN_SUPPLIED_PAPERS")
        if not reasons:
            reasons.append("BALANCED_HEURISTIC_SIGNAL")
        topic = row["topic"]
        results.append({
            "topic_id": topic.topic_id,
            "subject": topic.subject,
            "chapter": topic.chapter,
            "topic": topic.topic,
            "priority_score": _round(score, 2),
            "priority_score_label": "HEURISTIC STUDY PRIORITY — NOT PROBABILITY",
            "components": {
                "paper_occurrence_rate": _round(row["base_rate"]),
                "recency_weighted_rate": _round(row["recency_rate"]),
                "relative_mark_signal": _round(marks_signal),
                "omission_after_repeat_signal": _round(row["gap_signal"]),
                "official_syllabus_weight_signal": _round(row["syllabus_signal"]),
            },
            "papers_containing_topic": row["occurrence_count"],
            "gap_papers": row["gap_papers"],
            "reason_codes": reasons,
            "calibrated_probability": None,
        })
    results.sort(key=lambda item: (-item["priority_score"], item["topic_id"]))
    for index, item in enumerate(results, 1):
        item["rank"] = index
        item["study_tier"] = (
            "CORE PRIORITY" if index <= max(1, math.ceil(len(results) * 0.25))
            else "SECONDARY PRIORITY" if index <= max(2, math.ceil(len(results) * 0.60))
            else "SYLLABUS COVERAGE — DO NOT SKIP"
        )
    return results


def _actual_topics(paper: ExamPaper) -> set[str]:
    return {topic_id for question in paper.questions for topic_id in question.topic_ids}


def _raw_frequency_ranking(
    syllabus: Sequence[SyllabusTopic], papers: Sequence[ExamPaper]
) -> list[str]:
    """Simple historical-frequency baseline used only for honest comparison."""
    counts = Counter()
    for paper in papers:
        counts.update(_actual_topics(paper))
    return [
        topic.topic_id for topic in sorted(
            syllabus,
            key=lambda row: (-counts[row.topic_id], row.topic_id),
        )
    ]


def _score_bin(score: float) -> int:
    return min(4, max(0, int(max(0.0, min(99.999, score)) // 20)))


def _wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    denominator = 1 + (z * z / total)
    centre = (p + (z * z / (2 * total))) / denominator
    spread = z * math.sqrt((p * (1 - p) / total) + (z * z / (4 * total * total))) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


def _backtest(
    syllabus: Sequence[SyllabusTopic],
    papers: Sequence[ExamPaper],
    *,
    top_k: int,
    syllabus_hindsight_risk: bool,
    availability_dates_uncertain: bool,
    source_provenance_incomplete: bool,
) -> dict:
    splits: list[dict] = []
    outcome_pairs: list[tuple[float, int]] = []
    for held_index in range(2, len(papers)):
        held_out = papers[held_index]
        training = [
            paper for paper in papers[:held_index]
            if paper.available_from < held_out.held_on
        ]
        if len(training) < 2:
            continue
        ranking = _score_topics(syllabus, training)
        actual = _actual_topics(held_out)
        predicted = [row["topic_id"] for row in ranking[:top_k]]
        baseline_predicted = _raw_frequency_ranking(syllabus, training)[:top_k]
        hits = [topic for topic in predicted if topic in actual]
        baseline_hits = [topic for topic in baseline_predicted if topic in actual]
        recall = len(hits) / max(1, len(actual))
        baseline_recall = len(baseline_hits) / max(1, len(actual))
        precision = len(hits) / max(1, len(predicted))
        first_rank = next(
            (index for index, row in enumerate(ranking, 1) if row["topic_id"] in actual),
            None,
        )
        for row in ranking:
            outcome_pairs.append((row["priority_score"], int(row["topic_id"] in actual)))
        splits.append({
            "held_out_paper_id": held_out.paper_id,
            "held_out_date": held_out.held_on.isoformat(),
            "training_paper_count": len(training),
            "latest_training_date": max(row.held_on for row in training).isoformat(),
            "future_information_used": False,
            "top_k": top_k,
            "actual_topic_count": len(actual),
            "hit_count": len(hits),
            "top_k_recall": _round(recall),
            "raw_frequency_baseline_recall": _round(baseline_recall),
            "recall_delta_vs_raw_frequency": _round(recall - baseline_recall),
            "top_k_precision": _round(precision),
            "reciprocal_rank_first_hit": _round(1 / first_rank) if first_rank else 0.0,
        })

    bins: list[dict] = []
    for index in range(5):
        pairs = [pair for pair in outcome_pairs if _score_bin(pair[0]) == index]
        positives = sum(outcome for _, outcome in pairs)
        low, high = _wilson(positives, len(pairs))
        bins.append({
            "score_range": [index * 20, 100 if index == 4 else (index + 1) * 20],
            "samples": len(pairs),
            "observed": positives,
            "observed_frequency": _round(positives / len(pairs)) if pairs else None,
            "interval_low": _round(low),
            "interval_high": _round(high),
            "eligible_for_current_forecast": len(pairs) >= _MIN_BIN_SAMPLES,
        })

    enough = (
        len(splits) >= _MIN_CALIBRATION_SPLITS
        and len(outcome_pairs) >= _MIN_CALIBRATION_PAIRS
        and any(row["eligible_for_current_forecast"] for row in bins)
    )
    if syllabus_hindsight_risk:
        calibration_status = "BLOCKED_BY_SYLLABUS_HINDSIGHT_RISK"
    elif availability_dates_uncertain:
        calibration_status = "BLOCKED_BY_UNKNOWN_AVAILABILITY_DATES"
    elif source_provenance_incomplete:
        calibration_status = "BLOCKED_BY_INCOMPLETE_SOURCE_PROVENANCE"
    elif enough:
        calibration_status = "CALIBRATED_ON_WALK_FORWARD_HISTORY"
    else:
        calibration_status = "NOT_CALIBRATED"
    return {
        "status": "BACKTESTED" if splits else "INSUFFICIENT_HISTORY",
        "method": "expanding-window temporal holdout; each paper predicted from earlier available papers only",
        "splits": splits,
        "mean_top_k_recall": _round(mean(row["top_k_recall"] for row in splits)) if splits else None,
        "mean_raw_frequency_baseline_recall": _round(
            mean(row["raw_frequency_baseline_recall"] for row in splits)
        ) if splits else None,
        "mean_recall_delta_vs_raw_frequency": _round(
            mean(row["recall_delta_vs_raw_frequency"] for row in splits)
        ) if splits else None,
        "mean_top_k_precision": _round(mean(row["top_k_precision"] for row in splits)) if splits else None,
        "mean_reciprocal_rank": _round(mean(row["reciprocal_rank_first_hit"] for row in splits)) if splits else None,
        "calibration": {
            "status": calibration_status,
            "method": "fixed-bin empirical frequency with Wilson interval",
            "minimum_required_splits": _MIN_CALIBRATION_SPLITS,
            "minimum_required_outcome_pairs": _MIN_CALIBRATION_PAIRS,
            "held_out_splits": len(splits),
            "outcome_pairs": len(outcome_pairs),
            "bins": bins,
            "warning": "Historical calibration can drift after syllabus, policy or examiner changes; it is not certainty.",
        },
    }


def _apply_calibration(ranking: list[dict], calibration: Mapping[str, object]) -> None:
    if calibration.get("status") != "CALIBRATED_ON_WALK_FORWARD_HISTORY":
        return
    bins = list(calibration.get("bins") or [])
    for row in ranking:
        index = _score_bin(float(row["priority_score"]))
        if index >= len(bins):
            continue
        bucket = bins[index]
        if not bucket.get("eligible_for_current_forecast"):
            continue
        row["calibrated_probability"] = {
            "observed_frequency": bucket.get("observed_frequency"),
            "interval_low": bucket.get("interval_low"),
            "interval_high": bucket.get("interval_high"),
            "samples": bucket.get("samples"),
            "label": "BACKTEST-OBSERVED FREQUENCY — NOT A GUARANTEE",
        }


def _patterns(papers: Sequence[ExamPaper]) -> dict:
    topic_sets = [_actual_topics(paper) for paper in papers]
    similarities: list[float] = []
    for left, right in zip(topic_sets, topic_sets[1:]):
        union = left | right
        similarities.append(len(left & right) / len(union) if union else 0.0)
    formats = Counter(q.question_type for paper in papers for q in paper.questions)
    cognitive = Counter(q.cognitive_level for paper in papers for q in paper.questions)
    text_rows: dict[str, set[str]] = defaultdict(set)
    for paper in papers:
        for question in paper.questions:
            normalized = _normal_question(question.text)
            if normalized:
                text_rows[normalized].add(paper.paper_id)
    exact_repeats = sum(1 for ids in text_rows.values() if len(ids) >= 2)
    breadth = [len(row) for row in topic_sets]
    return {
        "inference_boundary": "OBSERVABLE PAPER-SELECTION PATTERNS ONLY",
        "boundary_note": "Past paper choices are observable; an examiner's private thoughts, intent or future choices are not observed.",
        "paper_count": len(papers),
        "mean_unique_topics_per_paper": _round(mean(breadth)) if breadth else 0.0,
        "consecutive_paper_topic_jaccard": _round(mean(similarities)) if similarities else None,
        "exact_question_text_repeats_across_papers": exact_repeats,
        "question_format_mix": dict(sorted(formats.items())),
        "cognitive_level_mix": dict(sorted(cognitive.items())),
        "interpretation": (
            "These distributions can support study-priority hypotheses. They cannot confirm which exact chapter/question will be selected."
        ),
    }


def _chapter_priorities(ranking: Sequence[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in ranking:
        grouped[(row["subject"], row["chapter"])].append(row)
    out: list[dict] = []
    for (subject, chapter), rows in grouped.items():
        scores = [float(row["priority_score"]) for row in rows]
        out.append({
            "subject": subject,
            "chapter": chapter,
            "chapter_priority_score": _round(mean(scores), 2),
            "score_label": "AGGREGATED STUDY PRIORITY — NOT PROBABILITY",
            "topic_count": len(rows),
            "top_topic_ids": [
                row["topic_id"] for row in sorted(
                    rows, key=lambda item: (-item["priority_score"], item["topic_id"])
                )[:5]
            ],
        })
    out.sort(
        key=lambda row: (-row["chapter_priority_score"], row["subject"], row["chapter"])
    )
    for index, row in enumerate(out, 1):
        row["rank"] = index
    return out


def _practice_blueprint(
    ranking: Sequence[dict], papers: Sequence[ExamPaper], *, limit: int
) -> list[dict]:
    out: list[dict] = []
    for priority in ranking[:limit]:
        topic_id = priority["topic_id"]
        matching = [
            question for paper in papers for question in paper.questions
            if topic_id in question.topic_ids
        ]
        formats = Counter(question.question_type for question in matching)
        cognitive = Counter(question.cognitive_level for question in matching)
        total = len(matching)
        out.append({
            "topic_id": topic_id,
            "topic": priority["topic"],
            "historical_question_count": total,
            "question_format_mix": {
                key: {
                    "count": value,
                    "share": _round(value / total) if total else None,
                }
                for key, value in sorted(formats.items())
            },
            "cognitive_level_mix": {
                key: {
                    "count": value,
                    "share": _round(value / total) if total else None,
                }
                for key, value in sorted(cognitive.items())
            },
            "practice_rule": (
                "Historical formats ke proportion mein practice karo, lekin har "
                "official syllabus topic ko cover karo; exact question predict nahi hua."
            ),
            "source_question_ids": [question.question_id for question in matching[:20]],
        })
    return out


def _hypothesis_id(kind: str, payload: object) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:10].upper()
    return f"EXAM-{kind}-{digest}"


def _hypotheses(ranking: Sequence[dict], patterns: Mapping[str, object], paper_count: int) -> list[dict]:
    if paper_count < 3 or not ranking:
        return []
    out: list[dict] = []

    def record(kind: str, payload: object, **fields) -> dict:
        return {
            "hypothesis_id": _hypothesis_id(kind, payload),
            "label": "APP-ORIGINAL EXAM HYPOTHESIS",
            "status": "UNTESTED — TEST NEXT",
            "supporting_observations": fields.pop("supporting_observations", []),
            "strongest_counterevidence": fields.pop(
                "strongest_counterevidence", "No prospective held-out confirmation yet."
            ),
            "assumptions": fields.pop("assumptions", [
                "Supplied papers and syllabus mappings are accurate and representative."
            ]),
            "boundary_conditions": fields.pop("boundary_conditions", [
                "Applies only to the named exam/syllabus version and supplied time period."
            ]),
            "primary_endpoint": fields.pop(
                "primary_endpoint", "Pre-registered next-paper top-k topic recall"
            ),
            "analysis_metric": fields.pop(
                "analysis_metric", "Recall difference with Wilson/bootstrap uncertainty"
            ),
            "replication_plan": fields.pop(
                "replication_plan", "Repeat on a later non-overlapping exam cycle."
            ),
            "confidence_label": "PROVISIONAL — NO SUCCESS PERCENTAGE",
            "human_review_required": True,
            **fields,
        }
    high_gap = next(
        (row for row in ranking if "LONG_OMISSION_AFTER_REPEAT" in row["reason_codes"]),
        None,
    )
    if high_gap:
        out.append(record(
            "ROTATION",
            high_gap["topic_id"],
            statement=f"{high_gap['topic']} jaise historically recurring par recently omitted topics matched topics se zyada often next papers mein return kar sakte hain.",
            derived_from=[high_gap["topic_id"], "paper occurrence", "omission gap"],
            supporting_observations=[
                f"{high_gap['topic_id']} historical occurrence and omission-gap signals"
            ],
            alternative_explanations=["syllabus change", "random sampling", "paper-setter change"],
            prediction="Pre-registered omitted-topic group ka next-paper hit rate matched non-omitted group se higher hoga.",
            prospective_test="Next 3 legally obtained papers se pehle groups freeze karo; top-k recall aur risk difference report karo.",
            falsification_rule="Agar next 3 papers mein omitted group ka hit rate matched group se higher na ho to hypothesis reject/downgrade karo.",
            success_threshold="Omitted group risk difference > 0 in the frozen 3-paper test.",
            failure_threshold="Risk difference <= 0 or mapping drift invalidates comparison.",
            safety_ethics="Public-paper observational test; no leaked material or private examiner data.",
            novelty_boundary="Dataset-specific hypothesis; global novelty checked nahi hai.",
        ))
    top_ids = [row["topic_id"] for row in ranking[: min(5, len(ranking))]]
    out.append(record(
        "PRIORITY",
        top_ids,
        statement="Frozen multi-signal priority ranking sirf raw frequency ranking se next-paper topic coverage behtar kar sakti hai.",
        derived_from=top_ids,
        supporting_observations=["Current expanding-window backtest and score components"],
        alternative_explanations=["small sample", "score-weight overfitting", "syllabus drift"],
        prediction="Next held-out papers par priority model ka top-k recall raw-frequency baseline se higher hoga.",
        prospective_test="Weights aur top-k ab freeze karke next 3 papers par both rankings ka paired comparison karo.",
        falsification_rule="Agar priority model raw-frequency baseline ko next 3 papers mein beat na kare to weights reject/recalibrate karo.",
        success_threshold="Mean recall delta versus frozen raw-frequency baseline > 0.",
        failure_threshold="Mean recall delta <= 0 across the prospective window.",
        safety_ethics="Public-paper observational test; no exam leak or unauthorized access.",
        novelty_boundary="Ranking-method test hai; exact questions ki prediction nahi.",
    ))
    formats = dict(patterns.get("question_format_mix") or {})
    if len(formats) >= 2:
        out.append(record(
            "FORMAT",
            formats,
            statement="Topic ke saath historical question-format mix include karne se practice-set transfer improve ho sakta hai.",
            derived_from=sorted(formats),
            supporting_observations=["Supplied-paper question-format distribution"],
            alternative_explanations=["format labels inconsistent", "online reconstruction errors"],
            prediction="Format-stratified practice group unseen mock/paper par equal-time topic-only group se higher accuracy dikhayega.",
            prospective_test="Same topics/time ke randomized practice sets; blinded scoring; pre-registered accuracy and time endpoints.",
            falsification_rule="Pre-registered minimum effect na mile ya confidence interval zero cross kare to hypothesis supported nahi.",
            primary_endpoint="Blinded unseen-paper accuracy at equal practice time",
            analysis_metric="Between-group accuracy difference with confidence interval",
            success_threshold="Pre-registered smallest educationally meaningful effect is exceeded.",
            failure_threshold="Effect is below threshold or interval includes the null.",
            safety_ethics="Voluntary informed consent, privacy protection, no effect on real grades or exam access.",
            novelty_boundary="Educational experiment proposal; effectiveness proven nahi.",
        ))
    return out[:3]


def _summary(result: Mapping[str, object]) -> str:
    priorities = list(result.get("study_priorities") or [])[:8]
    chapters = list(result.get("chapter_priorities") or [])[:5]
    lines = [
        "## Seedha jawab",
        "Ye exact-paper prediction ya examiner mind-reading nahi hai. Ye supplied official/public past papers aur syllabus se leakage-safe study priorities banata hai.",
        "",
        "## Study priority (probability nahi)",
    ]
    for row in priorities:
        lines.append(
            f"- #{row['rank']} {row['subject']} → {row['chapter']} → {row['topic']}: "
            f"priority {row['priority_score']}/100; {', '.join(row['reason_codes'])}"
        )
    if not priorities:
        lines.append("- Usable dated paper history nahi mili; priority calculate nahi hui.")
    lines.extend(["", "## Chapter priority"])
    for row in chapters:
        lines.append(
            f"- #{row['rank']} {row['subject']} → {row['chapter']}: "
            f"{row['chapter_priority_score']}/100 study priority."
        )
    if not chapters:
        lines.append("- Chapter ranking ke liye usable mapping nahi mili.")
    backtest = dict(result.get("walk_forward_backtest") or {})
    lines.extend([
        "",
        "## Backtest aur uncertainty",
        f"- Status: {backtest.get('status', 'NOT RUN')}.",
        f"- Mean top-k recall: {backtest.get('mean_top_k_recall')}.",
        f"- Calibration: {dict(backtest.get('calibration') or {}).get('status', 'NOT CALIBRATED')}.",
        "- Past pattern future paper ki guarantee nahi; syllabus/policy/paper-setter drift result badal sakta hai.",
        "",
        "## App ki apni exam hypotheses",
    ])
    for row in list(result.get("app_original_exam_hypotheses") or []):
        lines.append(f"- [{row['hypothesis_id']}] {row['statement']} Status: {row['status']}.")
    if not result.get("app_original_exam_hypotheses"):
        lines.append("- Data kam tha; app-original hypothesis invent nahi ki gayi.")
    return "\n".join(lines)


class ExamIntelligenceEngine:
    """Pure deterministic analyzer for a bounded, source-traceable exam corpus."""

    def analyze(
        self,
        *,
        exam_name: str,
        as_of: object,
        syllabus: Sequence[Mapping[str, object]],
        papers: Sequence[Mapping[str, object]],
        target_exam_date: object = None,
        syllabus_version: str = "",
        syllabus_published_at: object = None,
        top_k: int = 10,
    ) -> dict:
        name = _clean(exam_name, 200)
        if not name:
            raise ExamDataError("exam_name is required")
        cutoff = _as_date(as_of, "as_of")
        target = _as_date(target_exam_date, "target_exam_date", required=False)
        if target and target < cutoff:
            raise ExamDataError("target_exam_date cannot be before as_of")
        topic_rows = _topics(list(syllabus or []))
        parsed_papers = _papers(
            list(papers or []), topic_ids={topic.topic_id for topic in topic_rows}
        )
        future = [
            paper for paper in parsed_papers
            if paper.held_on >= cutoff or paper.available_from > cutoff
        ]
        usable = [paper for paper in parsed_papers if paper not in future]
        top_k = max(1, min(int(top_k or 10), len(topic_rows), 50))
        syllabus_date = _as_date(
            syllabus_published_at, "syllabus_published_at", required=False
        )
        first_possible_holdout = usable[2].held_on if len(usable) >= 3 else None
        hindsight = bool(
            syllabus_date and first_possible_holdout and syllabus_date >= first_possible_holdout
        )
        ranking = _score_topics(topic_rows, usable)
        availability_uncertain = any(
            paper.availability_assumed for paper in usable
        )
        provenance_incomplete = any(
            not paper.source_id or not paper.source_url for paper in usable
        )
        backtest = _backtest(
            topic_rows,
            usable,
            top_k=top_k,
            syllabus_hindsight_risk=hindsight,
            availability_dates_uncertain=availability_uncertain,
            source_provenance_incomplete=provenance_incomplete,
        )
        _apply_calibration(ranking, backtest["calibration"])
        patterns = _patterns(usable)
        hypotheses = _hypotheses(ranking, patterns, len(usable))
        chapter_priorities = _chapter_priorities(ranking)
        practice_blueprint = _practice_blueprint(
            ranking, usable, limit=min(top_k, 12)
        )
        source_ledger = [
            {
                "paper_id": paper.paper_id,
                "held_on": paper.held_on.isoformat(),
                "available_from": paper.available_from.isoformat(),
                "availability_assumption": (
                    "held_on used because available_from was not supplied"
                    if paper.availability_assumed else "explicit available_from supplied"
                ),
                "source_id": paper.source_id,
                "source_url": paper.source_url,
                "source_reference_status": (
                    "CALLER-SUPPLIED REFERENCE — NOT INDEPENDENTLY FETCHED BY THIS ANALYSIS"
                ),
                "question_count": len(paper.questions),
                "warnings": list(paper.source_warnings),
            }
            for paper in usable
        ]
        question_count = sum(len(paper.questions) for paper in usable)
        provenance_complete = sum(
            1 for paper in usable if paper.source_id and paper.source_url
        )
        data_quality = {
            "submitted_papers": len(parsed_papers),
            "usable_papers": len(usable),
            "usable_questions": question_count,
            "syllabus_topics": len(topic_rows),
            "source_provenance_complete_papers": provenance_complete,
            "source_provenance_coverage": _round(
                provenance_complete / len(usable) if usable else 0.0
            ),
            "availability_dates_assumed": sum(
                1 for paper in usable if paper.availability_assumed
            ),
            "history_start": usable[0].held_on.isoformat() if usable else None,
            "history_end": usable[-1].held_on.isoformat() if usable else None,
        }
        status = (
            "ASSESSMENT_READY" if len(usable) >= 3
            else "EXPLORATORY_ONLY" if usable
            else "INSUFFICIENT_DATA"
        )
        calibration_status = backtest["calibration"]["status"]
        forecast_readiness = (
            "CALIBRATED_WITH_INTERVALS"
            if calibration_status == "CALIBRATED_ON_WALK_FORWARD_HISTORY"
            else "BACKTESTED_NOT_CALIBRATED"
            if backtest["status"] == "BACKTESTED"
            else "RANKING_ONLY"
        )
        identity_payload = {
            "exam_name": name,
            "as_of": cutoff.isoformat(),
            "target": target.isoformat() if target else None,
            "syllabus": [asdict(topic) for topic in topic_rows],
            "papers": [
                {
                    "paper_id": paper.paper_id,
                    "held_on": paper.held_on.isoformat(),
                    "available_from": paper.available_from.isoformat(),
                    "questions": [asdict(q) for q in paper.questions],
                }
                for paper in usable
            ],
        }
        analysis_id = "EXAM-ANALYSIS-" + hashlib.sha256(
            json.dumps(identity_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16].upper()
        result = {
            "schema_version": SCHEMA_VERSION,
            "analysis_id": analysis_id,
            "status": status,
            "forecast_readiness": forecast_readiness,
            "exam_name": name,
            "as_of": cutoff.isoformat(),
            "target_exam_date": target.isoformat() if target else None,
            "syllabus_version": _clean(syllabus_version, 160) or "NOT_SUPPLIED",
            "data_quality": data_quality,
            "leakage_guard": {
                "passed": True,
                "rule": "Only papers held and available before each cutoff may train a forecast.",
                "future_records_excluded": len(future),
                "excluded_paper_ids": [paper.paper_id for paper in future],
                "syllabus_hindsight_risk": hindsight,
                "syllabus_published_at": syllabus_date.isoformat() if syllabus_date else None,
            },
            "existing_evidence": {
                "supplied_past_papers": [paper.paper_id for paper in usable],
                "official_syllabus_topics": [topic.topic_id for topic in topic_rows],
                "claim": "Only observable supplied records are summarized here.",
            },
            "study_priorities": ranking[:top_k],
            "chapter_priorities": chapter_priorities,
            "question_pattern_blueprint": practice_blueprint,
            "examiner_pattern_analysis": patterns,
            "walk_forward_backtest": backtest,
            "app_original_exam_hypotheses": hypotheses,
            "source_ledger": source_ledger,
            "honesty_boundary": {
                "allowed_claims": [
                    "ranked study priority",
                    "observable historical pattern",
                    "backtest-observed frequency only when calibrated",
                ],
                "forbidden_claims": [
                    "exact question confirmed",
                    "examiner mind read",
                    "guaranteed selection",
                    "success percentage without calibrated held-out evidence",
                ],
                "human_review_required": True,
            },
        }
        result["human_summary"] = _summary(result)
        return result


class ExamLedgerStore:
    """Small atomic project-isolated ledger for resumable exam analyses."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        max_records_per_project: int = 20,
    ) -> None:
        self.root = Path(root)
        self.max_records = max(1, min(int(max_records_per_project), 100))
        self._lock = threading.RLock()

    @staticmethod
    def _project_key(project_id: object) -> str:
        return hashlib.sha256(str(project_id or "").encode("utf-8")).hexdigest()

    def _path(self, project_id: object) -> Path:
        return self.root / f"{self._project_key(project_id)}.json"

    def history(self, project_id: object) -> list[dict]:
        path = self._path(project_id)
        with self._lock:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return []
            except OSError as exc:
                raise ExamDataError("exam ledger could not be read safely") from exc
            except (ValueError, TypeError) as exc:
                raise ExamDataError("exam ledger is corrupted; overwrite blocked") from exc
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            raise ExamDataError("exam ledger is invalid; overwrite blocked")
        rows = data.get("records") if isinstance(data, dict) else []
        return [dict(row) for row in rows if isinstance(row, dict)][-self.max_records :]

    def latest(self, project_id: object) -> dict | None:
        rows = self.history(project_id)
        return dict(rows[-1]) if rows else None

    def save(self, project_id: object, result: Mapping[str, object]) -> dict:
        if not str(project_id or "").strip():
            raise ExamDataError("project_id is required for ledger persistence")
        record = dict(result)
        if not record.get("analysis_id"):
            raise ExamDataError("analysis_id is required for ledger persistence")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(project_id)
        # Atomic replace protects readers; the OS lock prevents two Python
        # worker processes from racing through read/modify/write.
        with ExclusiveProcessFileLock(str(path) + ".lock"):
            with self._lock:
                rows = self.history(project_id)
                rows = [
                    row for row in rows
                    if row.get("analysis_id") != record["analysis_id"]
                ]
                rows.append(record)
                rows = rows[-self.max_records :]
                payload = {
                    "schema_version": 1,
                    "project_key": self._project_key(project_id),
                    "records": rows,
                }
                temp = path.with_suffix(".tmp")
                try:
                    temp.write_text(
                        json.dumps(
                            payload, ensure_ascii=False, indent=2, sort_keys=True
                        ),
                        encoding="utf-8",
                    )
                    os.replace(temp, path)
                finally:
                    try:
                        temp.unlink(missing_ok=True)
                    except OSError:
                        pass
        return {"saved": True, "records_retained": len(rows)}


__all__ = [
    "ExamDataError",
    "ExamIntelligenceEngine",
    "ExamLedgerStore",
    "ExamPaper",
    "ExamQuestion",
    "SyllabusTopic",
]
