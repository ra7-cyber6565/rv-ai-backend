"""Bounded structured-source reading for datasets and public code repositories.

The ordinary ContentFetcher is document-centric.  A catalogue landing page is
not a dataset read, and a repository README is not an implementation read.  This
module adds the missing structured paths while keeping the same fail-closed
truth boundary used elsewhere in the research engine.

Dataset rules
-------------
* inspect only public CSV/TSV/JSON/JSONL or provider-returned structured rows;
* cap bytes, rows, columns and cell length;
* record schema, sample rows and bounded numeric profile with provenance;
* a row sample is explicitly *not* the full dataset.

Code rules
----------
* inspect only public GitHub repositories already discovered by the dedicated
  connector;
* pin inspection to an exact public tree/commit identity;
* select a bounded number of source files, never clone/execute/build them;
* README alone can never satisfy CODE INSPECTED;
* file excerpts carry file + line locators.

Neither path upgrades claim truth.  It only changes the honest answer to
"what content did the engine actually inspect?".
"""
from __future__ import annotations

import base64
import csv
import io
import json
import math
import os
import re
from dataclasses import dataclass, field, fields as dataclass_fields
from statistics import fmean
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlparse

from .connectors import code_repository_connector as github_code
from .connectors.base import SLOW_TIMEOUT, http_get
from .content_fetcher import ContentFetcher
from .models import (
    ACCESS_DEPTH_EXPLAIN,
    ACCESS_SECTIONS,
    EvidencePack,
    Passage,
    SourceRecord,
    SourceType,
)
from .network_safety import (
    NetworkSafetyError,
    normalized_content_type,
    public_error,
    read_bounded_response,
    safe_get_with_redirects,
)

MAX_DATA_BYTES = 4 * 1024 * 1024
MAX_DATA_ROWS = 200
MAX_DATA_COLUMNS = 80
MAX_SAMPLE_ROWS = 8
MAX_CELL_CHARS = 240
MAX_CODE_TREE_BYTES = 8 * 1024 * 1024
MAX_CODE_FILE_BYTES = 128 * 1024
MAX_CODE_FILES = 5
MAX_CODE_EXCERPT_CHARS = 1800
MAX_STRUCTURED_PASSAGE_CHARS = 2400

_DATA_FORMATS = {"csv", "tsv", "json", "jsonl"}
_DATA_EXTENSIONS = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
}
_DATA_CONTENT_TYPES = {
    "text/csv": "csv",
    "application/csv": "csv",
    "text/tab-separated-values": "tsv",
    "application/json": "json",
    "application/ld+json": "json",
    "text/json": "json",
    "application/x-ndjson": "jsonl",
    "application/ndjson": "jsonl",
    # Some public-data servers declare a tabular file as plain text or octet
    # stream.  We accept those only when provider metadata/URL already supplied
    # a supported structured format hint.
    "text/plain": "",
    "application/octet-stream": "",
    "binary/octet-stream": "",
}

_CODE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".java", ".kt", ".kts", ".go", ".rs", ".c", ".cc", ".cpp", ".h",
    ".hpp", ".cs", ".rb", ".php", ".swift", ".scala", ".r", ".jl",
    ".sql", ".sh", ".bash", ".ps1", ".lua", ".dart", ".ex", ".exs",
    ".erl", ".hrl", ".fs", ".fsx", ".clj", ".cljs", ".groovy",
}
_CODE_BASENAMES = {
    "dockerfile", "makefile", "cmakelists.txt", "build.gradle",
    "build.gradle.kts", "pom.xml", "cargo.toml", "go.mod", "pyproject.toml",
    "package.json", "requirements.txt",
}
_CODE_SKIP_PARTS = {
    ".git", "node_modules", "vendor", "vendors", "dist", "build", "target",
    ".venv", "venv", "site-packages", "coverage", "generated", "third_party",
    "third-party", "fixtures", "snapshots",
}
_CODE_SKIP_SUFFIXES = {
    ".min.js", ".min.css", ".map", ".lock", ".sum", ".svg", ".png", ".jpg",
    ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".tar", ".jar", ".class",
}


def _bounded_text(value: object, limit: int = MAX_CELL_CHARS) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text[: max(1, int(limit))]


def _format_hint(url: str = "", hint: str = "") -> str:
    clean_hint = str(hint or "").strip().casefold().lstrip(".")
    aliases = {
        "comma separated values": "csv",
        "comma-separated values": "csv",
        "tab separated values": "tsv",
        "tab-separated values": "tsv",
        "ndjson": "jsonl",
        "json lines": "jsonl",
    }
    clean_hint = aliases.get(clean_hint, clean_hint)
    if clean_hint in _DATA_FORMATS:
        return clean_hint
    path = (urlparse(str(url or "")).path or "").casefold()
    for suffix, fmt in _DATA_EXTENSIONS.items():
        if path.endswith(suffix):
            return fmt
    return ""


def _query_terms(text: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[^\W_]{3,}", str(text or ""), re.UNICODE)
        if token
    }


def _safe_float(value: object) -> Optional[float]:
    raw = str(value if value is not None else "").strip().replace(",", "")
    if not raw or raw.casefold() in {"na", "n/a", "nan", "null", "none", "-"}:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass
class StructuredSourceRecord(SourceRecord):
    """SourceRecord with serializable structured-inspection proof fields.

    Keeping this as a subclass avoids changing the stable base API for sources
    that were never structurally inspected.  ``SourceRecord.to_dict()`` uses
    ``dataclasses.asdict(self)``, so these fields automatically survive into the
    final API/AI-1 packet without a side channel.
    """

    dataset_inspection: Dict = field(default_factory=dict)
    code_inspection: Dict = field(default_factory=dict)
    code_files: List[str] = field(default_factory=list)

    @property
    def has_structured_inspection(self) -> bool:
        return bool(self.dataset_inspection or self.code_inspection or self.code_files)

    def access_depth(self) -> str:
        if self.has_structured_inspection:
            # A bounded dataset sample / selected repository files are relevant
            # sections, never whole-artifact full text.
            if self.series_meta and super().access_depth() != "METADATA ONLY":
                # MarketSeries connectors may truly read their complete bounded
                # provider series window.  Preserve their existing honest depth.
                return super().access_depth()
            return ACCESS_SECTIONS
        return super().access_depth()

    def access_depth_note(self) -> str:
        if self.has_structured_inspection and not self.series_meta:
            return f"{ACCESS_SECTIONS} — {ACCESS_DEPTH_EXPLAIN[ACCESS_SECTIONS]}"
        return super().access_depth_note()

    def citation_label(self) -> str:
        label = super().citation_label()
        if self.code_inspection:
            detail = "bounded public code files inspect hue; execute/test nahi hua"
        elif self.dataset_inspection:
            if self.series_meta:
                detail = "provider series values inspect hue"
            else:
                detail = "bounded structured data rows inspect hue; poora dataset nahi"
        else:
            return label
        if "padha gaya:" in label:
            prefix = label.rsplit("padha gaya:", 1)[0].rstrip(" ,")
            return f"{prefix}, padha gaya: {detail}"
        return f"{label}, {detail}"


def _as_structured(source: SourceRecord) -> StructuredSourceRecord:
    if isinstance(source, StructuredSourceRecord):
        return source
    values = {
        item.name: getattr(source, item.name)
        for item in dataclass_fields(SourceRecord)
    }
    return StructuredSourceRecord(**values)


def _extract_tabular_json(payload) -> Tuple[List[Dict], Optional[int]]:
    """Return the first defensible list-of-records plus an optional total."""
    total: Optional[int] = None
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in ("total", "count", "total_count", "recordsTotal"):
            try:
                if payload.get(key) is not None:
                    total = int(payload.get(key))
                    break
            except (TypeError, ValueError):
                pass
        rows = None
        for key in ("records", "data", "results", "result", "value", "items", "rows"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                rows = candidate
                break
            if isinstance(candidate, dict):
                nested, nested_total = _extract_tabular_json(candidate)
                if nested:
                    return nested, total if total is not None else nested_total
        if rows is None:
            # A single record is still structured data, but we label it one row.
            scalarish = {k: v for k, v in payload.items()
                         if not isinstance(v, (dict, list, tuple, set))}
            rows = [scalarish] if scalarish else []
    else:
        rows = []

    clean: List[Dict] = []
    for row in rows or []:
        if isinstance(row, dict):
            clean.append({str(k): v for k, v in row.items()})
        elif isinstance(row, (list, tuple)):
            clean.append({f"col_{idx + 1}": value for idx, value in enumerate(row)})
        else:
            clean.append({"value": row})
        if len(clean) >= MAX_DATA_ROWS:
            break
    return clean, total


def _parse_csv_rows(text: str, *, delimiter: str = ",") -> List[Dict]:
    stream = io.StringIO(str(text or ""))
    reader = csv.DictReader(stream, delimiter=delimiter)
    if not reader.fieldnames:
        return []
    rows: List[Dict] = []
    for row in reader:
        rows.append({str(k): v for k, v in (row or {}).items() if k is not None})
        if len(rows) >= MAX_DATA_ROWS:
            break
    return rows


def _parse_jsonl_rows(text: str) -> List[Dict]:
    rows: List[Dict] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            rows.append({"value": value})
        if len(rows) >= MAX_DATA_ROWS:
            break
    return rows


def _profile_rows(rows: Sequence[Dict]) -> Dict:
    columns: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            name = str(key)
            if name not in seen:
                seen.add(name)
                columns.append(name)
            if len(columns) >= MAX_DATA_COLUMNS:
                break
        if len(columns) >= MAX_DATA_COLUMNS:
            break

    missing: Dict[str, int] = {column: 0 for column in columns}
    numeric_values: Dict[str, List[float]] = {column: [] for column in columns}
    samples: List[Dict] = []
    for index, row in enumerate(rows):
        clipped: Dict[str, str] = {}
        for column in columns:
            value = row.get(column)
            text = _bounded_text(value)
            if not text:
                missing[column] += 1
            number = _safe_float(value)
            if number is not None:
                numeric_values[column].append(number)
            if index < MAX_SAMPLE_ROWS:
                clipped[column] = text
        if index < MAX_SAMPLE_ROWS:
            samples.append(clipped)

    numeric: Dict[str, Dict] = {}
    for column, values in numeric_values.items():
        # Require at least two numeric observations and a meaningful share of the
        # inspected rows; otherwise IDs/dates with one accidental number would
        # be mislabeled as quantitative variables.
        if len(values) < 2 or len(values) < max(2, len(rows) // 3):
            continue
        numeric[column] = {
            "n": len(values),
            "min": min(values),
            "max": max(values),
            "mean": fmean(values),
        }
        if len(numeric) >= 12:
            break

    return {
        "rows_inspected": len(rows),
        "columns": columns,
        "column_count": len(columns),
        "missing_counts": missing,
        "numeric_profile": numeric,
        "sample_rows": samples,
    }


def _dataset_excerpt(profile: Dict, *, fmt: str, resource_url: str,
                     total_rows: Optional[int] = None) -> str:
    lines = [
        f"Structured dataset inspection ({fmt or 'unknown format'}).",
        f"Rows inspected: {profile.get('rows_inspected', 0)}"
        + (f" / provider-reported {total_rows}" if total_rows is not None else "")
        + ".",
        "Columns: " + ", ".join(profile.get("columns", [])[:30]),
    ]
    numeric = profile.get("numeric_profile") or {}
    if numeric:
        parts = []
        for key, stats in list(numeric.items())[:8]:
            parts.append(
                f"{key}: n={stats.get('n')} min={stats.get('min'):g} "
                f"max={stats.get('max'):g} mean={stats.get('mean'):g}")
        lines.append("Numeric profile: " + " | ".join(parts))
    for idx, row in enumerate(profile.get("sample_rows") or [], start=1):
        compact = "; ".join(f"{key}={value}" for key, value in row.items())
        lines.append(f"Sample row {idx}: {compact}")
    lines.append(
        "Boundary: yeh bounded row inspection hai; isse poora dataset padha/validated "
        "ya causal claim proven nahi maana gaya.")
    return "\n".join(lines)[:MAX_STRUCTURED_PASSAGE_CHARS]


def _code_path_ok(path: str, size: int) -> bool:
    clean = str(path or "").strip().replace("\\", "/")
    if not clean or size <= 0 or size > MAX_CODE_FILE_BYTES:
        return False
    low = clean.casefold()
    parts = {part.casefold() for part in low.split("/")[:-1]}
    if parts & _CODE_SKIP_PARTS:
        return False
    if any(low.endswith(suffix) for suffix in _CODE_SKIP_SUFFIXES):
        return False
    base = low.rsplit("/", 1)[-1]
    if base in {"readme", "readme.md", "readme.rst", "readme.txt"}:
        return False
    if base in _CODE_BASENAMES:
        return True
    return any(low.endswith(suffix) for suffix in _CODE_SUFFIXES)


def _score_code_path(path: str, query_terms: set[str]) -> Tuple[int, int, str]:
    low = str(path or "").casefold()
    tokens = _query_terms(low.replace("/", " ").replace(".", " "))
    overlap = len(tokens & query_terms)
    depth = low.count("/")
    # Source directories are usually more implementation-relevant than tests,
    # examples or config when query overlap is tied.  Tests are still allowed;
    # they simply lose the tiebreaker.
    bonus = 2 if any(part in low.split("/") for part in ("src", "lib", "app", "core")) else 0
    penalty = 2 if any(part in low.split("/") for part in ("test", "tests", "example", "examples")) else 0
    return overlap * 10 + bonus - penalty, -depth, low


def _code_excerpt(text: str, query: str, path: str) -> Tuple[str, str]:
    lines = str(text or "").splitlines()
    if not lines:
        return "", ""
    terms = _query_terms(query)
    hits: List[Tuple[int, int]] = []
    for idx, line in enumerate(lines):
        score = len(_query_terms(line) & terms) if terms else 0
        if score:
            hits.append((score, idx))
    if hits:
        hits.sort(key=lambda row: (-row[0], row[1]))
        center = hits[0][1]
        start = max(0, center - 12)
    else:
        # No textual hit: show the beginning of an already path-relevant source
        # file, which usually contains imports/types/API surface.  This is still
        # code inspection, not query entailment.
        start = 0
    end = min(len(lines), start + 42)
    numbered = [f"{i + 1}: {lines[i]}" for i in range(start, end)]
    excerpt = "\n".join(numbered)
    if len(excerpt) > MAX_CODE_EXCERPT_CHARS:
        excerpt = excerpt[:MAX_CODE_EXCERPT_CHARS].rsplit("\n", 1)[0]
    locator = f"{path}:L{start + 1}-L{min(end, len(lines))}"
    return excerpt, locator


class StructuredSourceInspector:
    """Inspect structured evidence already selected into an EvidencePack."""

    def __init__(self, allow_network: Optional[bool] = None):
        if allow_network is None:
            flag = os.getenv("ALLOW_STRUCTURED_FETCH", "true").strip().casefold()
            allow_network = flag not in {"false", "0", "no", "off"}
        self.allow_network = bool(allow_network)

    def _requests(self):
        import requests
        return requests

    def _public_resource(self, url: str, *, format_hint: str = "") -> Dict:
        """Read one untrusted public data-resource URL with DNS/redirect SSRF guard."""
        if not self.allow_network:
            return {"ok": False, "reason": "structured network fetch config se band hai"}
        response = None
        try:
            response, final_url = safe_get_with_redirects(
                self._requests(),
                url,
                headers={"User-Agent": "InfinityResearchAI/1.0 public dataset reader"},
                timeout=SLOW_TIMEOUT,
                stream=True,
                resolve_dns=True,
                max_redirects=3,
            )
            status = int(getattr(response, "status_code", 200) or 200)
            if status >= 400:
                return {"ok": False, "reason": f"public dataset resource HTTP {status}"}
            content_type = normalized_content_type(response)
            hinted = _format_hint(final_url, format_hint)
            typed = _DATA_CONTENT_TYPES.get(content_type)
            if content_type and content_type not in _DATA_CONTENT_TYPES:
                return {"ok": False, "reason": "resource structured text/JSON type nahi thi"}
            fmt = hinted or typed or ""
            if fmt not in _DATA_FORMATS:
                return {"ok": False, "reason": "resource format CSV/TSV/JSON/JSONL confirm nahi hua"}
            raw = read_bounded_response(response, MAX_DATA_BYTES)
            if not raw:
                return {"ok": False, "reason": "dataset resource khaali thi"}
            text = raw.decode("utf-8-sig", errors="replace")
            if "\x00" in text[:2000]:
                return {"ok": False, "reason": "dataset resource binary lagi, text rows nahi"}
            return {
                "ok": True,
                "url": final_url,
                "format": fmt,
                "bytes": len(raw),
                "text": text,
                "content_type": content_type,
            }
        except Exception as exc:
            return {"ok": False, "reason": public_error(exc)}
        finally:
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass

    @staticmethod
    def _pick_resource(resources: Iterable[Dict]) -> Dict:
        candidates: List[Tuple[int, int, Dict]] = []
        rank = {"csv": 0, "tsv": 1, "jsonl": 2, "json": 3}
        for raw in resources or []:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or raw.get("download_url") or raw.get("href")
                      or raw.get("content") or "").strip()
            fmt = _format_hint(url, str(raw.get("format") or raw.get("type") or
                                         raw.get("key") or raw.get("name") or ""))
            if not url or fmt not in _DATA_FORMATS:
                continue
            try:
                size = int(raw.get("size") or raw.get("bytes") or 0)
            except (TypeError, ValueError):
                size = 0
            if size and size > MAX_DATA_BYTES:
                continue
            candidates.append((rank.get(fmt, 9), size or MAX_DATA_BYTES, {
                "url": url,
                "format": fmt,
                "provider_name": str(raw.get("name") or raw.get("key") or ""),
                "provider_size": size,
            }))
        candidates.sort(key=lambda row: (row[0], row[1], row[2]["url"]))
        return dict(candidates[0][2]) if candidates else {}

    def _zenodo_resource(self, source: SourceRecord) -> Dict:
        match = re.search(r"/records?/(\d+)", str(source.url or ""))
        if not match or not self.allow_network:
            return {}
        record_id = match.group(1)
        try:
            payload = http_get(
                f"https://zenodo.org/api/records/{record_id}", timeout=SLOW_TIMEOUT).json()
        except Exception:
            return {}
        resources = []
        for item in (payload or {}).get("files") or []:
            if not isinstance(item, dict):
                continue
            links = item.get("links") if isinstance(item.get("links"), dict) else {}
            resources.append({
                "url": links.get("content") or links.get("self") or "",
                "format": item.get("key") or "",
                "name": item.get("key") or "",
                "size": item.get("size") or 0,
            })
        picked = self._pick_resource(resources)
        if picked:
            picked["route"] = "zenodo_public_file"
        return picked

    def _data_gov_resource(self, source: SourceRecord) -> Dict:
        match = re.search(r"/dataset/([^/?#]+)", str(source.url or ""))
        if not match or not self.allow_network:
            return {}
        slug = match.group(1)
        try:
            payload = http_get(
                "https://catalog.data.gov/api/3/action/package_show",
                params={"id": slug}, timeout=SLOW_TIMEOUT).json()
        except Exception:
            return {}
        result = (payload or {}).get("result") if isinstance(payload, dict) else {}
        resources = result.get("resources") if isinstance(result, dict) else []
        picked = self._pick_resource(resources or [])
        if picked:
            picked["route"] = "data_gov_public_resource"
        return picked

    def _huggingface_resource(self, source: SourceRecord) -> Dict:
        match = re.search(r"huggingface\.co/datasets/([^/?#]+/[^/?#]+)",
                          str(source.url or ""))
        if not match or not self.allow_network:
            return {}
        repo_id = match.group(1)
        try:
            payload = http_get(
                f"https://huggingface.co/api/datasets/{quote(repo_id, safe='/')}/tree/main",
                params={"recursive": "false", "expand": "false", "limit": 100},
                timeout=SLOW_TIMEOUT).json()
        except Exception:
            return {}
        resources = []
        rows = payload if isinstance(payload, list) else []
        for item in rows:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("rfilename") or item.get("name") or "")
            if not path:
                continue
            resources.append({
                "url": (f"https://huggingface.co/datasets/{repo_id}/resolve/main/"
                        f"{quote(path, safe='/')}"),
                "format": path,
                "name": path,
                "size": item.get("size") or 0,
            })
        picked = self._pick_resource(resources)
        if picked:
            picked["route"] = "huggingface_public_file"
        return picked

    def _who_rows(self, source: SourceRecord) -> Dict:
        match = re.fullmatch(
            r"https://ghoapi\.azureedge\.net/api/([A-Za-z0-9_.-]+)",
            str(source.url or "").strip())
        if not match or not self.allow_network:
            return {}
        code = match.group(1)
        try:
            payload = http_get(
                f"https://ghoapi.azureedge.net/api/{code}",
                params={"$top": MAX_DATA_ROWS}, timeout=SLOW_TIMEOUT).json()
        except Exception:
            return {}
        rows, total = _extract_tabular_json(payload)
        if not rows:
            return {}
        return {
            "rows": rows,
            "total_rows": total,
            "format": "json",
            "resource_url": f"https://ghoapi.azureedge.net/api/{code}",
            "bytes": 0,
            "route": "who_gho_odata_rows",
        }

    @staticmethod
    def _series_rows(source: SourceRecord) -> List[Dict]:
        meta = source.series_meta or {}
        points = meta.get("points") or meta.get("observations") or []
        rows: List[Dict] = []
        for item in points:
            if isinstance(item, dict):
                period = item.get("period") or item.get("date") or item.get("time")
                value = item.get("value")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                period, value = item[0], item[1]
            else:
                continue
            rows.append({"period": period, "value": value})
            if len(rows) >= MAX_DATA_ROWS:
                break
        return rows

    def _dataset_rows(self, source: SourceRecord) -> Dict:
        series = self._series_rows(source)
        if series:
            return {
                "rows": series,
                "total_rows": len((source.series_meta or {}).get("points") or series),
                "format": "series_meta",
                "resource_url": source.url,
                "bytes": 0,
                "route": "provider_series_meta",
            }

        who = self._who_rows(source)
        if who:
            return who

        plan: Dict = {}
        connector = str(source.connector or "")
        if connector == "zenodo":
            plan = self._zenodo_resource(source)
        elif connector == "data_gov":
            plan = self._data_gov_resource(source)
        elif connector == "huggingface":
            plan = self._huggingface_resource(source)
        if not plan:
            direct_fmt = _format_hint(source.url)
            if direct_fmt:
                plan = {"url": source.url, "format": direct_fmt,
                        "route": "direct_public_structured_url"}
        if not plan:
            return {"reason": "public structured resource route nahi mila"}

        fetched = self._public_resource(plan.get("url", ""),
                                        format_hint=plan.get("format", ""))
        if not fetched.get("ok"):
            return {"reason": fetched.get("reason", "resource read fail")}
        fmt = str(fetched.get("format") or "")
        text = str(fetched.get("text") or "")
        total = None
        if fmt == "csv":
            rows = _parse_csv_rows(text, delimiter=",")
        elif fmt == "tsv":
            rows = _parse_csv_rows(text, delimiter="\t")
        elif fmt == "jsonl":
            rows = _parse_jsonl_rows(text)
        else:
            try:
                payload = json.loads(text)
            except Exception:
                return {"reason": "JSON parse nahi hua"}
            rows, total = _extract_tabular_json(payload)
        if not rows:
            return {"reason": "structured resource me usable rows nahi mile"}
        return {
            "rows": rows,
            "total_rows": total,
            "format": fmt,
            "resource_url": fetched.get("url") or plan.get("url") or source.url,
            "bytes": int(fetched.get("bytes") or 0),
            "route": plan.get("route") or "public_structured_resource",
        }

    def inspect_dataset(self, source: SourceRecord) -> Dict:
        payload = self._dataset_rows(source)
        rows = payload.get("rows") or []
        if not rows:
            return {"ok": False, "reason": payload.get("reason") or "dataset rows nahi mile"}
        profile = _profile_rows(rows)
        if not profile.get("rows_inspected") or not profile.get("columns"):
            return {"ok": False, "reason": "dataset profile banane layak rows/columns nahi mile"}
        total = payload.get("total_rows")
        excerpt = _dataset_excerpt(
            profile, fmt=str(payload.get("format") or ""),
            resource_url=str(payload.get("resource_url") or source.url),
            total_rows=total if isinstance(total, int) else None)
        inspection = {
            "status": "DATA_INSPECTED",
            "route": payload.get("route") or "",
            "format": payload.get("format") or "",
            "resource_url": payload.get("resource_url") or source.url,
            "bytes_read": int(payload.get("bytes") or 0),
            "rows_inspected": profile["rows_inspected"],
            "row_limit": MAX_DATA_ROWS,
            "columns": profile["columns"],
            "column_count": profile["column_count"],
            "missing_counts": profile["missing_counts"],
            "numeric_profile": profile["numeric_profile"],
            "sample_rows": profile["sample_rows"],
            "provider_reported_total_rows": total if isinstance(total, int) else None,
            "bounded": True,
            "complete_dataset": False,
            "truth_boundary": (
                "row/sample inspection != full dataset validation; correlation/profile != causation"
            ),
        }
        return {"ok": True, "inspection": inspection, "excerpt": excerpt,
                "locator": f"dataset rows 1-{profile['rows_inspected']}"}

    @staticmethod
    def _github_repo_parts(source: SourceRecord) -> Tuple[str, str]:
        match = re.fullmatch(r"https://github\.com/([^/]+)/([^/?#]+?)(?:\.git)?/?",
                             str(source.url or "").strip())
        if not match:
            return "", ""
        return match.group(1), match.group(2)

    def inspect_code(self, source: SourceRecord, question: str) -> Dict:
        if not self.allow_network:
            return {"ok": False, "reason": "structured network fetch config se band hai"}
        owner, repo = self._github_repo_parts(source)
        if not owner or not repo:
            return {"ok": False, "reason": "public GitHub owner/repo URL parse nahi hua"}
        base = f"{github_code.GITHUB_API}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        try:
            meta = github_code.github_json(base, max_bytes=2 * 1024 * 1024)
            default_branch = str((meta or {}).get("default_branch") or "main")
            tree = github_code.github_json(
                f"{base}/git/trees/{quote(default_branch, safe='')}",
                params={"recursive": "1"}, max_bytes=MAX_CODE_TREE_BYTES)
        except Exception as exc:
            return {"ok": False, "reason": f"GitHub code tree read fail: {type(exc).__name__}"}

        rows = (tree or {}).get("tree") or []
        query_terms = _query_terms(question)
        candidates: List[Tuple[Tuple[int, int, str], Dict]] = []
        for item in rows:
            if not isinstance(item, dict) or item.get("type") != "blob":
                continue
            path = str(item.get("path") or "")
            try:
                size = int(item.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            if not _code_path_ok(path, size):
                continue
            candidates.append((_score_code_path(path, query_terms), item))
        candidates.sort(key=lambda row: (-row[0][0], -row[0][1], row[0][2]))

        excerpts: List[Dict] = []
        inspected_files: List[str] = []
        bytes_inspected = 0
        commit_sha = str((tree or {}).get("sha") or "")
        for _score, item in candidates:
            if len(inspected_files) >= MAX_CODE_FILES:
                break
            path = str(item.get("path") or "")
            try:
                payload = github_code.github_json(
                    f"{base}/contents/{quote(path, safe='/')}",
                    params={"ref": commit_sha or default_branch},
                    max_bytes=2 * 1024 * 1024)
            except Exception:
                continue
            if not isinstance(payload, dict) or str(payload.get("encoding") or "") != "base64":
                continue
            raw_content = str(payload.get("content") or "").replace("\n", "")
            try:
                raw = base64.b64decode(raw_content, validate=False)
            except Exception:
                continue
            if not raw or len(raw) > MAX_CODE_FILE_BYTES or b"\x00" in raw[:2000]:
                continue
            text = raw.decode("utf-8", errors="replace")
            excerpt, locator = _code_excerpt(text, question, path)
            if not excerpt:
                continue
            inspected_files.append(path)
            bytes_inspected += len(raw)
            excerpts.append({"path": path, "locator": locator, "text": excerpt})

        if not inspected_files:
            return {"ok": False, "reason": "repository tree mila par bounded source-code file inspect nahi hua"}

        rendered = []
        for entry in excerpts:
            rendered.append(f"[{entry['locator']}]\n{entry['text']}")
        rendered.append(
            "Boundary: selected public code files sirf padhe gaye; repository clone/build/"
            "execute/test nahi hua aur selected files ko poora repository nahi maana gaya.")
        excerpt_text = "\n\n".join(rendered)[:MAX_STRUCTURED_PASSAGE_CHARS]
        inspection = {
            "status": "CODE_INSPECTED",
            "repository": f"{owner}/{repo}",
            "default_branch": default_branch,
            "tree_sha": commit_sha,
            "tree_truncated": bool((tree or {}).get("truncated")),
            "tree_blob_count": sum(1 for row in rows if isinstance(row, dict)
                                   and row.get("type") == "blob"),
            "eligible_code_files": len(candidates),
            "files_inspected": len(inspected_files),
            "file_limit": MAX_CODE_FILES,
            "bytes_inspected": bytes_inspected,
            "code_files": inspected_files,
            "bounded": True,
            "repository_complete": False,
            "executed": False,
            "tests_run": False,
            "truth_boundary": (
                "code read != executed/tested; selected files != whole repository; README != code proof"
            ),
        }
        return {"ok": True, "inspection": inspection, "excerpt": excerpt_text,
                "files": inspected_files,
                "passages": excerpts,
                "locator": excerpts[0]["locator"] if excerpts else ""}

    @staticmethod
    def _replace_source(pack: EvidencePack, index: int,
                        source: StructuredSourceRecord) -> None:
        pack.sources[index] = source

    @staticmethod
    def _replace_passages(pack: EvidencePack, source_id: str,
                          passages: Sequence[Passage]) -> None:
        pack.passages[:] = [p for p in pack.passages if p.source_id != source_id]
        pack.passages.extend(passages)

    def enrich(self, pack: EvidencePack, *, max_sources: int = 3,
               budget_chars: int = 2400) -> Dict:
        report = {
            "attempted": 0,
            "succeeded": 0,
            "dataset_inspected": 0,
            "code_inspected": 0,
            "failed": 0,
            "entries": [],
            "note": "",
        }
        if not pack.sources or max_sources <= 0:
            report["note"] = "Structured reading nahi chali — source/budget nahi tha."
            return report

        candidates: List[Tuple[int, SourceRecord]] = []
        for index, source in enumerate(pack.sources):
            is_dataset = source.source_type == SourceType.DATASET
            is_code = str(source.connector or "") == "github_code"
            if is_dataset or is_code:
                candidates.append((index, source))
        # Make sure one family cannot starve the other when both are present.
        candidates.sort(key=lambda row: (
            0 if str(row[1].connector or "") == "github_code" else 1,
            -float(row[1].combined_score or 0.0),
            row[0],
        ))
        limit = max(1, int(max_sources))

        for index, original in candidates[:limit]:
            report["attempted"] += 1
            source = _as_structured(original)
            if str(source.connector or "") == "github_code":
                result = self.inspect_code(source, pack.question)
                family = "code"
            else:
                result = self.inspect_dataset(source)
                family = "dataset"

            entry = {
                "source_id": source.source_id,
                "title": source.title[:90],
                "family": family,
                "ok": bool(result.get("ok")),
                "reason": result.get("reason", ""),
            }
            report["entries"].append(entry)
            if not result.get("ok"):
                report["failed"] += 1
                continue

            if family == "code":
                source.code_inspection = dict(result.get("inspection") or {})
                source.code_files = list(result.get("files") or [])
                source.read_note = (
                    f"Public GitHub repo ke {len(source.code_files)} bounded code file(s) "
                    f"exact tree {source.code_inspection.get('tree_sha') or 'unknown'} par inspect hue; "
                    "repo clone/build/execute/test nahi hua, poora repository padha nahi maana gaya."
                )
                source.snippet = str(result.get("excerpt") or "")[: budget_chars + 300]
                source.locator = str(result.get("locator") or source.locator)
                passages = [Passage(
                    source_id=source.source_id,
                    text=str(row.get("text") or "")[:MAX_STRUCTURED_PASSAGE_CHARS],
                    locator=str(row.get("locator") or ""),
                    provenance="public_code_file_excerpt",
                    # Kept conservative: claim promotion must not mistake a
                    # selected code file for whole-repository full text.
                    read_level_at_capture="snippet",
                ) for row in (result.get("passages") or [])]
                report["code_inspected"] += 1
            else:
                source.dataset_inspection = dict(result.get("inspection") or {})
                source.read_note = (
                    f"{source.dataset_inspection.get('rows_inspected', 0)} bounded structured row(s) "
                    f"inspect hue ({source.dataset_inspection.get('format') or 'format unknown'}); "
                    "poora dataset padha/validated nahi maana gaya aur profile causal proof nahi hai."
                )
                source.snippet = str(result.get("excerpt") or "")[: budget_chars + 300]
                source.locator = str(result.get("locator") or source.locator)
                passages = [Passage(
                    source_id=source.source_id,
                    text=source.snippet[:MAX_STRUCTURED_PASSAGE_CHARS],
                    locator=source.locator,
                    provenance="structured_dataset_rows",
                    read_level_at_capture="snippet",
                )]
                report["dataset_inspected"] += 1

            self._replace_source(pack, index, source)
            self._replace_passages(pack, source.source_id, passages)
            report["succeeded"] += 1

        if report["attempted"]:
            report["note"] = (
                f"{report['succeeded']}/{report['attempted']} structured source inspect hue "
                f"(dataset {report['dataset_inspected']}, code {report['code_inspected']}); "
                "samples/selected files ko full dataset/repo nahi maana gaya."
            )
        else:
            report["note"] = "Pack me dataset/code-repository source nahi tha; structured read apply nahi hui."
        return report


class StructuredAwareContentFetcher(ContentFetcher):
    """Drop-in ContentFetcher that runs structured reading after document reading."""

    def __init__(self, allow_network: Optional[bool] = None):
        super().__init__(allow_network=allow_network)
        self.structured = StructuredSourceInspector(allow_network=self.allow_network)
        self.last_structured_report: Dict = {}

    def enrich(self, pack: EvidencePack, max_sources: int = 3,
               budget_chars: int = 2400) -> Dict:
        report = super().enrich(pack, max_sources=max_sources,
                                budget_chars=budget_chars)
        structured = self.structured.enrich(
            pack,
            max_sources=max(1, int(max_sources)),
            budget_chars=budget_chars,
        )
        self.last_structured_report = structured
        report["structured"] = structured
        note = str(report.get("note") or "").strip()
        structured_note = str(structured.get("note") or "").strip()
        if structured_note:
            report["note"] = (f"{note} | Structured: {structured_note}"
                              if note else f"Structured: {structured_note}")
        return report
