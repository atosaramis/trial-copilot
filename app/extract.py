"""Read a protocol PDF into a trial card.

Pipeline (build spec sections 3, 4 and 8):
1. `pdftotext -layout` gives the full text, one string per PDF page.
2. Clean it: Unicode normalisation, the redaction junk word, and change-history
   blocks (summary of changes, amendment history, revision history) are removed.
3. Find the visit-schedule pages and render up to 3 of them with `pdftoppm -png -r 150`.
4. Muse Spark 1.3 reads the full text into the card fields (JSON, reasoning_effort
   "minimal"), and reads the schedule page images for the visit fields.
5. Code merges both, checks page citations, and sums per-arm enrollment when the
   protocol gives no total. `app/design_checks.py` then checks the design numbers (conflicting
   enrollment totals, single-arm designs, site counts that are only planning assumptions).

Usage:  python -m app.extract protocol.pdf [--out card.json] [--runs-dir DIR] [--dry-run]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

from .card_schema import (BOOL_FIELDS, CARD_FIELDS, ENUMS, FORBIDDEN_KEY_WORDS, INT_FIELDS,
                          NUM_FIELDS, STR_FIELDS, TEXT_FIELDS, VISION_FIELDS, CODE_VISIT_FIELDS)
from . import design_checks
from .ages import parse_age_criterion
from .visits import count_visits, procedure_is_mandated, procedure_purpose, screening_window_from_visits

MODEL = "muse-spark-1.3"
BASE_URL = "https://api.meta.ai/v1"
PRICE_IN, PRICE_OUT, PRICE_CACHED = 1.25e-6, 4.25e-6, 0.15e-6  # USD per token, standard rate
PRICES = {  # USD per token: input, output, cached input
    "muse-spark-1.3": (PRICE_IN, PRICE_OUT, PRICE_CACHED),
    "muse-spark-1.3-contributor": (0.10e-6, 0.20e-6, 0.10e-6),
}
# Scans (little or no text layer) of at least SCAN_MIN_PAGES pages are read from page images;
# shorter ones are stubs and get no protocol features (preregistration.md).
LOW_TEXT_CHARS_PER_PAGE = 300
SCAN_MIN_PAGES = 10
SCAN_MAX_IMAGES = 10
# The model's context is 1,048,576 tokens; at the worst measured 3.25 characters per token this
# keeps the text call under about 860K tokens. Longer texts are trimmed from the end and flagged.
MAX_TEXT_CHARS = 2_800_000
PROMPTS = Path(__file__).parent / "prompts"
MAX_SCHEDULE_IMAGES = 8  # whole schedule table: visit counts need every column
# Schedule fields that may fall back to the text reading when the schedule call gives null.
TEXT_FALLBACK_FIELDS = ("inpatient_stay_required",)
PROCEDURE_FIELDS = ("mandatory_fresh_biopsy", "soc_invasive_procedures_first_26_weeks",
                    "research_invasive_procedures_first_26_weeks")

# ---------------------------------------------------------------- text cleanup
JUNK_WORDS = re.compile(r"\b5HGDFWHG\b")
_MOJIBAKE_HINT = re.compile("[\u00c2\u00c3\u00e2][\u0080-\u00bf\u2018-\u203a\u20ac\u2122]")


def fix_mojibake(s: str) -> str:
    """Undo UTF-8 text that was decoded as cp1252 (e.g. 'â‰¤' -> '≤')."""
    if not s or not _MOJIBAKE_HINT.search(s):
        return s
    try:
        return s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def normalise_text(s: str) -> str:
    s = fix_mojibake(s)
    s = unicodedata.normalize("NFKC", s)
    s = JUNK_WORDS.sub("", s)
    return s


def pdf_pages(pdf: str | Path) -> list[str]:
    """Full `pdftotext -layout` text, one string per PDF page (page 1 = index 0)."""
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], check=True,
                         capture_output=True).stdout.decode("utf-8", "replace")
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]  # pdftotext ends with a form feed
    return [normalise_text(p) for p in pages]


DOT_LEADER = re.compile(r"\.{6,}|(?:\. ){5,}")


def is_toc_page(page: str) -> bool:
    return sum(1 for line in page.splitlines() if DOT_LEADER.search(line)) >= 4


CHANGE_TITLE = re.compile(
    r"summary of (?:protocol |the )?changes|amendment history|revision history|change history"
    r"|document history|history of (?:changes|amendments|revisions)"
    r"|protocol amendment\b.*\bsummary|rationale for .*\bamendment", re.I)
HEADING = re.compile(
    r"^\s*(?:(?P<appx>appendix\s+(?P<anum>\d+|[A-Z])\b\.?)|(?P<num>\d+(?:\.\d+)*)\.?(?=\s))?\s*(?P<title>\S.*)$",
    re.I)
NUMBERED_HEADING = re.compile(r"^\s*(?P<num>\d+(?:\.\d+)*)\.?\s+[A-Z][A-Za-z]")
APPENDIX_AMENDMENT = re.compile(r"(?:protocol )?amendments?\b", re.I)
APPENDIX_HEADING = re.compile(r"^\s*appendix\s+(?P<anum>\d+|[A-Z])\b", re.I)


def _appx_value(a: str) -> int:
    return int(a) if a.isdigit() else ord(a.upper()) - 64


def _is_heading_line(line: str) -> bool:
    s = line.strip()
    return 0 < len(s) <= 110 and not DOT_LEADER.search(s)


def strip_change_history(pages: list[str]) -> tuple[list[str], list[dict]]:
    """Remove change-history blocks, keeping one string per page so page numbers stay true.

    A block starts at a short heading line whose title matches CHANGE_TITLE (never on a
    table-of-contents page). It ends at the next heading of the same or higher level:
    for "Appendix n" blocks, the next appendix with a higher number; for numbered
    sections, the next numbered heading with the same or fewer levels; for un-numbered
    titles, the next top-level numbered heading or appendix. Otherwise it runs to the end.
    """
    lines: list[tuple[int, str]] = []
    for pi, p in enumerate(pages):
        for line in p.split("\n"):
            lines.append((pi, line))
    toc = [is_toc_page(p) for p in pages]
    keep = [True] * len(lines)
    removed: list[dict] = []
    i = 0
    while i < len(lines):
        pi, line = lines[i]
        m = HEADING.match(line) if (_is_heading_line(line) and not toc[pi]) else None
        title = (m.group("title") or "") if m else ""
        is_change = bool(m) and (CHANGE_TITLE.search(title) is not None or (
            m.group("anum") is not None and APPENDIX_AMENDMENT.match(title) is not None))
        if not is_change:
            i += 1
            continue
        anum = m.group("anum")
        num = m.group("num")
        level = num.count(".") + 1 if num else None
        j = i + 1
        while j < len(lines):
            pj, lj = lines[j]
            if toc[pj] and pj != pi:
                break
            if _is_heading_line(lj):
                am = APPENDIX_HEADING.match(lj)
                nm = NUMBERED_HEADING.match(lj)
                if anum is not None:
                    if am and _appx_value(am.group("anum")) > _appx_value(anum):
                        break
                elif level is not None:
                    if nm and nm.group("num").count(".") + 1 <= level and not CHANGE_TITLE.search(lj):
                        break
                    if am:
                        break
                else:
                    if (nm and "." not in nm.group("num")) or am:
                        break
            j += 1
        for k in range(i, j):
            keep[k] = False
        removed.append({"title": re.sub(r"\s+", " ", line.strip())[:80],
                        "first_page": pi + 1, "last_page": lines[j - 1][0] + 1})
        i = j
    out = [[] for _ in pages]
    marked = set()
    for k, (pi, line) in enumerate(lines):
        if keep[k]:
            out[pi].append(line)
        elif pi not in marked:
            out[pi].append("[change-history text removed]")
            marked.add(pi)
    return ["\n".join(x) for x in out], removed


# ------------------------------------------------------ visit-schedule pages
SPEC_SCHEDULE_RX = re.compile(
    r"schedule of (assessments|activities|events)|time and events|study flow ?chart", re.I)
# Extra headings seen in real protocols (e.g. "Visit evaluation schedule",
# "Schedule of Evaluations / Study Calendar", "Study Plan").
EXTRA_SCHEDULE_RX = re.compile(
    r"visit (evaluation )?schedule|schedule of (evaluations|study procedures|procedures|visits)"
    r"|study calendar|study plan\b|table of (assessments|events)|flow ?chart", re.I)
GRID_MARK = re.compile(r"(?<!\S)[Xx\u2713\u2714\u221a\u2022](?!\S)")
MIN_GRID = 5            # check marks for a page to count as part of a table
MIN_EXTRA_BLOCK = 20    # a second table block must have at least this many marks


def grid_score(page: str) -> int:
    return len(GRID_MARK.findall(page))


def find_schedule_pages(pages: list[str], max_pages: int = MAX_SCHEDULE_IMAGES) -> dict:
    """Find the visit-schedule table pages. Returns 1-based PDF page numbers.

    Title hits come from the spec regex plus a few extra headings. A "block" is a run of
    consecutive non-contents pages that look like a check-mark grid. Blocks count if they
    contain a title hit or start right after one. We keep the first and last page of the
    biggest block (visit numbers usually run across pages, so the last page shows the final
    visit), then the first page of other sizeable blocks, then the rest in page order.
    """
    toc = [is_toc_page(p) for p in pages]
    spec_hits = [i + 1 for i, p in enumerate(pages) if not toc[i] and SPEC_SCHEDULE_RX.search(p)]
    extra_hits = [i + 1 for i, p in enumerate(pages) if not toc[i] and EXTRA_SCHEDULE_RX.search(p)]
    hits = sorted(set(spec_hits) | set(extra_hits))
    scores = {i + 1: grid_score(p) for i, p in enumerate(pages)}
    grid = [n for n in scores if scores[n] >= MIN_GRID and not toc[n - 1]]
    blocks: list[list[int]] = []
    for n in grid:
        if blocks and blocks[-1][-1] == n - 1:
            blocks[-1].append(n)
        else:
            blocks.append([n])
    hit_set = set(hits)
    attached = [b for b in blocks if hit_set & set(b) or (b[0] - 1) in hit_set]
    attached.sort(key=lambda b: (-sum(scores[n] for n in b), b[0]))
    # Keep the biggest block, plus other blocks only if they are real tables.
    attached = attached[:1] + [b for b in attached[1:] if sum(scores[n] for n in b) >= MIN_EXTRA_BLOCK]
    order: list[int] = []
    if attached:
        top = attached[0]
        order += [top[0], top[-1]]
        others = attached[1:]
        order += [b[0] for b in others]
        order += top[1:-1]
        for b in others:
            order += b[1:]
    elif hits:
        order = sorted(hits, key=lambda n: (-scores[n], n))[:1]
    selected: list[int] = []
    for n in order:
        if n not in selected:
            selected.append(n)
    selected = sorted(selected[:max_pages])
    all_pages = sorted({n for b in attached for n in b})
    return {
        "selected": selected,
        "all_schedule_pages": all_pages,
        "truncated": len(all_pages) > len(selected),
        "title_hits_spec_regex": spec_hits,
        "title_hits_extra_regex": sorted(set(extra_hits) - set(spec_hits)),
        "found_by": ("spec_regex" if any(set(b) & set(spec_hits) or (b[0] - 1) in spec_hits
                                         for b in attached[:1]) else
                     "extra_regex" if attached or hits else "not_found"),
    }


def render_pages(pdf: str | Path, page_numbers: list[int], outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("page-*.png"):
        old.unlink()
    paths = []
    for n in page_numbers:
        prefix = outdir / f"page-{n:03d}"
        subprocess.run(["pdftoppm", "-png", "-r", "150", "-f", str(n), "-l", str(n),
                        "-singlefile", str(pdf), str(prefix)], check=True, capture_output=True)
        paths.append(prefix.with_suffix(".png"))
    return paths


def text_payload(pages: list[str]) -> str:
    return "\n".join(f"=== PAGE {i + 1} ===\n{p}" for i, p in enumerate(pages))


def text_payload_subset(pages: list[str], page_numbers: list[int]) -> str:
    return "\n".join(f"=== PAGE {n} ===\n{pages[n - 1]}" for n in page_numbers if 1 <= n <= len(pages))


# ------------------------------------------------------------------ API calls
class MuseError(RuntimeError):
    pass


def _client():
    from openai import OpenAI
    key = os.environ.get("META_API_KEY")
    if not key:
        raise MuseError("META_API_KEY is not set in the environment")
    return OpenAI(base_url=BASE_URL, api_key=key, timeout=600, max_retries=0)


def cost_usd(usage: dict | None, model: str = MODEL) -> float:
    if not usage:
        return 0.0
    p_in, p_out, p_cached = PRICES.get(model, PRICES[MODEL])
    cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    pin = usage.get("prompt_tokens", 0) - cached
    return round(pin * p_in + cached * p_cached + usage.get("completion_tokens", 0) * p_out, 6)


def call_muse(messages: list, raw_path: Path, max_completion_tokens: int = 6000,
              client=None, model: str = MODEL) -> dict:
    """One streamed JSON call. Raw chunks and usage are written to raw_path before parsing."""
    client = client or _client()
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ttft = None
    parts: list[str] = []
    usage = None
    finish = None
    error = None
    with open(raw_path, "w") as raw:
        try:
            stream = client.chat.completions.create(
                model=model, messages=messages, stream=True,
                stream_options={"include_usage": True},
                response_format={"type": "json_object"},
                reasoning_effort="minimal",
                max_completion_tokens=max_completion_tokens)
            for chunk in stream:
                d = chunk.model_dump()
                raw.write(json.dumps(d) + "\n")
                if d.get("usage"):
                    usage = d["usage"]
                for ch in d.get("choices") or []:
                    c = (ch.get("delta") or {}).get("content")
                    if c:
                        if ttft is None:
                            ttft = time.time() - t0
                        parts.append(c)
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
        except Exception as e:  # noqa: BLE001 - recorded, then raised so the caller can inspect it
            error = f"{type(e).__name__}: {getattr(e, 'status_code', '')} {str(e)[:400]}"
            raw.write(json.dumps({"error": error}) + "\n")
        latency = round(time.time() - t0, 1)
        raw.write(json.dumps({"_summary": {"latency_s": latency, "usage": usage,
                                           "finish_reason": finish}}) + "\n")
    rec = {"model": model, "reasoning_effort": "minimal", "latency_s": latency,
           "ttft_s": round(ttft, 1) if ttft else None, "usage": usage,
           "cost_usd": cost_usd(usage, model), "finish_reason": finish, "raw": str(raw_path)}
    if error:
        rec["error"] = error
        raise MuseError(json.dumps(rec))
    content = "".join(parts)
    rec["content"] = content
    return rec


def load_raw(raw_path: Path, model: str = MODEL) -> dict | None:
    """Rebuild a finished call from its saved raw stream (no API call, no new spend)."""
    if not raw_path.exists():
        return None
    parts, summary = [], None
    for line in raw_path.read_text().splitlines():
        d = json.loads(line)
        if "error" in d:
            return None
        if "_summary" in d:
            summary = d["_summary"]
            continue
        for ch in d.get("choices") or []:
            c = (ch.get("delta") or {}).get("content")
            if c:
                parts.append(c)
    if not summary or not summary.get("usage") or summary.get("finish_reason") != "stop":
        return None
    u = summary["usage"]
    return {"model": model, "reasoning_effort": "minimal", "latency_s": summary["latency_s"],
            "ttft_s": None, "usage": u, "cost_usd": cost_usd(u, model), "finish_reason": "stop",
            "raw": str(raw_path), "reused_saved_response": True, "content": "".join(parts)}


def parse_json(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content or "", re.S)
        if m:
            return json.loads(m.group(0))
        raise


# ---------------------------------------------------------------- post-process
_ENUM_SYNONYMS = {
    "masking": {"open label": "None (Open Label)", "open-label": "None (Open Label)",
                "none": "None (Open Label)", "single blind": "Single", "double blind": "Double",
                "double-blind": "Double", "triple blind": "Triple", "quadruple blind": "Quadruple"},
    "allocation": {"randomised": "Randomized", "non-randomised": "Non-Randomized",
                   "nonrandomized": "Non-Randomized", "single group": "Single group",
                   "single-arm": "Single group", "single arm": "Single group"},
    "phase": {"phase ii": "Phase 2", "phase iii": "Phase 3", "phase i": "Phase 1",
              "phase iv": "Phase 4", "phase 1b": "Phase 1", "phase 2a": "Phase 2",
              "phase 2b": "Phase 2", "phase 3b": "Phase 3", "phase ii/iii": "Phase 2/3",
              "phase i/ii": "Phase 1/2"},
}


def _coerce(field: str, v, flags: list):
    if v is None or v == "" or v == "null":
        return None
    if field in ENUMS:
        if v in ENUMS[field]:
            return v
        s = str(v).strip()
        for allowed in ENUMS[field]:
            if s.lower() == allowed.lower():
                return allowed
        syn = _ENUM_SYNONYMS.get(field, {}).get(s.lower())
        if syn:
            return syn
        flags.append(f"{field}: value '{s[:40]}' not in allowed list, set to null")
        return None
    if field in INT_FIELDS:
        try:
            return int(round(float(str(v).replace(",", ""))))
        except ValueError:
            flags.append(f"{field}: '{str(v)[:40]}' is not a number, set to null")
            return None
    if field in NUM_FIELDS:
        try:
            f = float(str(v).replace(",", ""))
            return int(f) if f.is_integer() else f
        except ValueError:
            flags.append(f"{field}: '{str(v)[:40]}' is not a number, set to null")
            return None
    if field in BOOL_FIELDS:
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "yes"):
            return True
        if s in ("false", "no"):
            return False
        flags.append(f"{field}: '{s[:40]}' is not true/false, set to null")
        return None
    if field in STR_FIELDS:
        return normalise_text(str(v)).strip()
    if field == "visit_schedule":
        return v if isinstance(v, dict) else None
    if field == "invasive_procedures":
        out = []
        for p in v if isinstance(v, list) else []:
            if not isinstance(p, dict) or not p.get("name"):
                continue
            model_purpose = "research_only" if str(p.get("purpose") or "").lower().startswith("research") \
                else "standard_of_care"
            q = dict(p, name=normalise_text(str(p["name"]))[:80], purpose=model_purpose,
                     mandatory=p.get("mandatory") is True)
            # Code decides purpose and mandatory from the quoted wording (Day 2/3 fixes); the
            # model's reading is kept next to it so the user can see both.
            purpose, mandated = procedure_purpose(q), procedure_is_mandated(q)
            q.update(model_purpose=model_purpose, model_mandatory=q["mandatory"], purpose=purpose,
                     mandatory=mandated, decided_by="code from quoted wording")
            if purpose != model_purpose:
                flags.append(f"invasive procedure '{q['name'][:40]}': purpose set to {purpose} from its wording "
                             f"(model read {model_purpose})")
            if mandated != q["model_mandatory"]:
                why = ("is not a requirement" if not mandated else "is an explicit requirement")
                flags.append(f"invasive procedure '{q['name'][:40]}': wording "
                             f"'{str(q.get('requirement_wording'))[:40]}' {why}; set to "
                             f"{'mandated' if mandated else 'not mandated'}")
            out.append(q)
        return out
    if field == "schedule_of_assessments_pages":
        vals = v if isinstance(v, list) else [v]
        out = []
        for x in vals:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                pass
        return sorted(set(out))
    if field == "enrollment_per_arm":
        out = []
        for a in v if isinstance(v, list) else []:
            if isinstance(a, dict) and a.get("n") is not None:
                try:
                    out.append({"arm": normalise_text(str(a.get("arm") or "")) or None,
                                "n": int(float(str(a["n"]).replace(",", "")))})
                except ValueError:
                    pass
        return out
    return v


def _page_list(v, n_pages: int, flags: list, key: str) -> list[int]:
    vals = v if isinstance(v, list) else [v]
    out = []
    for x in vals:
        try:
            p = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= p <= n_pages:
            out.append(p)
        else:
            flags.append(f"_pages.{key}: page {p} is outside the document (1-{n_pages}), dropped")
    return sorted(set(out))


def merge_card(text_out: dict, vision_out: dict | None, n_pages: int,
               schedule: dict) -> tuple[dict, dict, dict, list]:
    """Combine text and schedule outputs into the card, with sources, citations and flags.

    The schedule call transcribes the visit schedule; code counts the visits from it.
    """
    flags: list[str] = []
    card: dict = {}
    pages: dict = {}
    source: dict = {}
    for k in list(text_out) + list(vision_out or {}):
        if any(w in k.lower() for w in FORBIDDEN_KEY_WORDS):
            flags.append(f"dropped forbidden key '{k}'")
    tp = text_out.get("_pages") or {}
    vp = (vision_out or {}).get("_pages") or {}
    for f in TEXT_FIELDS + VISION_FIELDS:
        if f in VISION_FIELDS and vision_out is not None:
            raw = ({k: vision_out.get(k) for k in ("screening_visits", "periods", "schedule_notes")}
                   if f == "visit_schedule" else vision_out.get(f))
            card[f] = _coerce(f, raw, flags)
            cites = (vp.get("periods") or vp.get("screening_visits") or vp.get("visit_schedule")
                     if f == "visit_schedule" else vp.get(f))
            if f == "screening_window_days" and cites is None:
                cites = vp.get("screening_visits")
            src = "vision"
        else:
            card[f] = _coerce(f, text_out.get(f), flags)
            cites = tp.get(f)
            src = "text"
        if (src == "vision" and card[f] is None and f in TEXT_FALLBACK_FIELDS
                and text_out.get(f) is not None):
            card[f] = _coerce(f, text_out.get(f), flags)
            cites = tp.get(f)
            src = "text"
            flags.append(f"{f}: not readable from the schedule pages, taken from the text")
        if f == "enrollment_per_arm" and card[f] is None:
            card[f] = []
        if f == "invasive_procedures" and card[f] is None and vision_out is not None:
            card[f] = []
        empty = card[f] is None or card[f] == []
        source[f] = "none" if empty else src
        if not empty:
            plist = _page_list(cites, n_pages, flags, f) if cites is not None else []
            if f == "schedule_of_assessments_pages" and not plist:
                plist = list(card[f])
            if f == "visit_schedule" and not plist:
                plist = list(card.get("schedule_of_assessments_pages") or schedule.get("selected") or [])
            if plist:
                pages[f] = plist
            elif card[f] != "Not applicable":
                flags.append(f"{f}: value has no page citation")
    # Schedule page numbers must be among the pages we sent.
    if vision_out is not None:
        shown = set(schedule.get("selected") or []) | set(schedule.get("text_pages") or [])
        for f in VISION_FIELDS:
            if f in pages and source.get(f) == "vision":
                bad = [p for p in pages[f] if p not in shown]
                if bad:
                    flags.append(f"_pages.{f}: cites pages {bad} that were not among the pages sent")
                    good = [p for p in pages[f] if p in shown]
                    if good:
                        pages[f] = good
                    else:
                        del pages[f]
    # Inpatient stay: yes if either reading says yes (the schedule call can miss a stay that the
    # text describes, e.g. admission for a required surgery). Both readings stay in crosscheck.
    if vision_out is not None:
        for f in TEXT_FALLBACK_FIELDS:
            tv = _coerce(f, text_out.get(f), [])
            if tv is True and card.get(f) is False:
                card[f] = True
                source[f] = "code"
                if tp.get(f) is not None:
                    pages[f] = sorted(set(pages.get(f, [])) | set(_page_list(tp.get(f), n_pages, [], f)))
                flags.append(f"{f}: schedule pages say no, text says yes; set to yes")
    # Screening window: when the schedule call leaves it blank, code works it out from the
    # screening visits' own timing (e.g. COPD Visit 1 at Week -4 gives 28 days). Day 2 fix.
    if vision_out is not None:
        coded = screening_window_from_visits(vision_out.get("screening_visits"))
        if card.get("screening_window_days") is None and coded is not None:
            card["screening_window_days"] = coded
            source["screening_window_days"] = "code"
            vcites = vp.get("screening_visits") or vp.get("periods")
            if vcites is not None:
                pages["screening_window_days"] = _page_list(vcites, n_pages, [], "screening_window_days")
            flags.append(f"screening_window_days: not stated by the schedule call; code read {coded} "
                         "days from the screening visits' timing")
        elif coded is not None and card.get("screening_window_days") != coded:
            flags.append(f"screening_window_days: schedule call read {card.get('screening_window_days')}, "
                         f"screening visits' timing gives {coded}")
    # Code counts visits and procedures (spec section 12, Oct 27 field definitions).
    procs = card.get("invasive_procedures") if vision_out is not None else None
    counts = count_visits(card.get("visit_schedule"), procs)
    for f in CODE_VISIT_FIELDS:
        card[f] = counts.get(f)
        source[f] = "none" if card[f] is None else "code"
        src_pages = (pages.get("invasive_procedures") or pages.get("visit_schedule")
                     if f in PROCEDURE_FIELDS else pages.get("visit_schedule"))
        if card[f] is not None and src_pages:
            pages[f] = src_pages
    # No schedule pages: the research-biopsy flag falls back to the text reading.
    if card["mandatory_fresh_biopsy"] is None and text_out.get("mandatory_fresh_biopsy") is not None:
        card["mandatory_fresh_biopsy"] = _coerce("mandatory_fresh_biopsy", text_out.get("mandatory_fresh_biopsy"), flags)
        source["mandatory_fresh_biopsy"] = "text"
        if tp.get("mandatory_fresh_biopsy") is not None:
            pages["mandatory_fresh_biopsy"] = _page_list(tp.get("mandatory_fresh_biopsy"), n_pages, flags,
                                                         "mandatory_fresh_biopsy")
    if card["major_procedure_required"]:
        flags.append("major procedure: " + "; ".join(
            f"{m['label']} (study day {m['day']}{', estimated' if m['day_estimated'] else ''})"
            for m in counts["major_procedures"] if not m["conditional"]))
    flags += [f"visit schedule: {n}" for n in counts["notes"]]
    # Age: code applies the registry convention to the quoted criterion ("Age > 18" -> 18).
    lo, hi = parse_age_criterion(card.get("age_criterion"))
    for f, v in (("min_age_years", lo), ("max_age_years", hi)):
        if v is not None:
            if card[f] is not None and card[f] != v:
                flags.append(f"{f}: model read {card[f]}, code read {v} from the age criterion")
            card[f] = v
            source[f] = "code"
            if "age_criterion" in pages:
                pages[f] = pages["age_criterion"]
    # Code sums per-arm enrollment when the protocol gives no total (spec section 8).
    if card["planned_enrollment"] is None and card["enrollment_per_arm"]:
        card["planned_enrollment"] = sum(a["n"] for a in card["enrollment_per_arm"])
        source["planned_enrollment"] = "code"
        if "enrollment_per_arm" in pages:
            pages["planned_enrollment"] = pages["enrollment_per_arm"]
        flags.append("planned_enrollment: summed from enrollment_per_arm by code")
    card = {f: card[f] for f in CARD_FIELDS}
    return card, pages, source, flags


def crosscheck(text_out: dict, card: dict) -> dict:
    """Text-only reading of the schedule fields, kept next to the schedule-call values."""
    out = {}
    for f in ["mandatory_fresh_biopsy", "inpatient_stay_required", "schedule_of_assessments_pages"]:
        tv = _coerce(f, text_out.get(f), [])
        out[f] = {"text": tv, "vision": card.get(f), "agree": tv == card.get(f)}
    return out


# ------------------------------------------------------------------ main entry
def sha256_file(p: str | Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def classify_pdf(pages: list[str]) -> str:
    """"text", "scan" (read from page images) or "stub" (too short to read; no protocol features)."""
    n = len(pages)
    chars = sum(len(p.strip()) for p in pages)
    if n and chars / n >= LOW_TEXT_CHARS_PER_PAGE:
        return "text"
    return "scan" if n >= SCAN_MIN_PAGES else "stub"


def extract(pdf: str | Path, runs_dir: str | Path = "cache/runs", dry_run: bool = False,
            vision: bool = True, reuse: bool = False, model: str = MODEL, client=None) -> dict:
    """Run the pipeline. reuse=True rebuilds calls from saved raw responses when present."""
    pdf = Path(pdf)
    digest = sha256_file(pdf)
    run_dir = Path(runs_dir).resolve() / f"{pdf.stem}-{digest[:12]}"
    raw_pages = pdf_pages(pdf)
    kind = classify_pdf(raw_pages)
    if kind != "text":
        return _extract_scan(pdf, digest, run_dir, raw_pages, kind, dry_run, reuse, model, client)
    pages, removed = strip_change_history(raw_pages)
    schedule = find_schedule_pages(pages)
    images = render_pages(pdf, schedule["selected"], run_dir / "pages") if schedule["selected"] else []
    payload = text_payload(pages)
    trimmed = None
    if len(payload) > MAX_TEXT_CHARS:
        trimmed = {"chars_before": len(payload), "chars_after": MAX_TEXT_CHARS}
        payload = payload[:MAX_TEXT_CHARS]
    source = {"file": pdf.name, "pdf_sha256": digest, "n_pages": len(pages), "kind": "text",
              "text_chars_sent": len(payload), "change_history_removed": removed,
              "schedule": schedule, "images": [str(p) for p in images]}
    if trimmed:
        source["text_trimmed"] = trimmed
    result = {"source": source, "runs": []}
    if dry_run:
        return result

    def _call(messages, raw_name, max_tokens):
        nonlocal client
        rec = load_raw(run_dir / raw_name, model) if reuse else None
        if rec is None:
            client = client or _client()
            rec = call_muse(messages, run_dir / raw_name, max_completion_tokens=max_tokens,
                            client=client, model=model)
        return rec

    prompt = (PROMPTS / "trial_card_text.txt").read_text()
    text_rec = _call(
        [{"role": "user", "content": prompt + "\n\n=== FULL PROTOCOL TEXT ===\n" + payload}],
        "text.raw.jsonl", 6000)
    text_out = parse_json(text_rec.pop("content"))
    text_rec["step"] = "text"
    result["runs"].append(text_rec)

    if not schedule["selected"] and not dry_run:
        # Fallback: the page finder found no grid (e.g. a garbled text layer), but the text call
        # named the schedule pages. Use those (PDF page numbers), capped like the finder.
        named = sorted({n for n in (text_out.get("schedule_of_assessments_pages") or [])
                        if isinstance(n, int) and 1 <= n <= len(pages)})
        if named:
            schedule.update(selected=named[:MAX_SCHEDULE_IMAGES], all_schedule_pages=named,
                            truncated=len(named) > MAX_SCHEDULE_IMAGES, found_by="text_call_pages")
            images = render_pages(pdf, schedule["selected"], run_dir / "pages")
            source["images"] = [str(p) for p in images]

    vision_out = None
    if schedule["selected"]:
        # One call transcribes the schedule: page images (unless --no-vision) plus their text layer.
        sel = schedule["selected"]
        use_images = vision and bool(images)
        page_list = "\n".join((f"- Image {i + 1} = PDF page {n}" if use_images else f"- PDF page {n} (text only)")
                              for i, n in enumerate(sel))
        if schedule["truncated"]:
            page_list += ("\nThe schedule also spans PDF pages "
                          f"{schedule['all_schedule_pages']}; only the pages above are shown.")
        vprompt = (PROMPTS / "visit_schedule_vision.txt").read_text().replace("{page_list}", page_list)
        content = [{"type": "text", "text": vprompt}]
        if use_images:
            for i, (n, img) in enumerate(zip(sel, images)):
                content.append({"type": "text", "text": f"Image {i + 1}: PDF page {n}"})
                b64 = base64.b64encode(img.read_bytes()).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        # Footnotes often run onto the page after the table, so its text is added too.
        after = schedule["all_schedule_pages"][-1] + 1 if schedule["all_schedule_pages"] else sel[-1] + 1
        text_pages = sorted(set(sel) | ({after} if after <= len(pages) else set()))
        schedule["text_pages"] = text_pages
        content.append({"type": "text", "text": "=== TEXT LAYER OF THE SAME PAGES (plus the next page, "
                        "for footnotes) ===\n" + text_payload_subset(pages, text_pages)})
        vrec = _call([{"role": "user", "content": content}],
                     "schedule.raw.jsonl" if use_images else "schedule_text.raw.jsonl", 8000)
        vision_out = parse_json(vrec.pop("content"))
        vrec["step"] = "schedule" if use_images else "schedule_text_only"
        result["runs"].append(vrec)
    else:
        source["vision_skipped"] = "no visit-schedule pages found"

    card, cites, field_source, flags = merge_card(text_out, vision_out, len(pages), schedule)
    design_checks.apply(card, cites, field_source, flags, text_out, pages)
    if trimmed:
        flags.append(f"protocol text trimmed from {trimmed['chars_before']:,} to {trimmed['chars_after']:,} "
                     "characters to fit the model's context")
    result.update({"card": card, "_pages": cites, "_field_source": field_source,
                   "flags": flags, "visit_crosscheck": crosscheck(text_out, card)})
    _totals(result)
    (run_dir / "card.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    return result


def _totals(result: dict) -> None:
    result["totals"] = {
        "latency_s": round(sum(r["latency_s"] for r in result["runs"]), 1),
        "prompt_tokens": sum((r["usage"] or {}).get("prompt_tokens", 0) for r in result["runs"]),
        "completion_tokens": sum((r["usage"] or {}).get("completion_tokens", 0) for r in result["runs"]),
        "cost_usd": round(sum(r["cost_usd"] for r in result["runs"]), 4),
    }


def _extract_scan(pdf: Path, digest: str, run_dir: Path, raw_pages: list[str], kind: str,
                  dry_run: bool, reuse: bool, model: str, client) -> dict:
    """Scanned protocol: the text prompt reads the first SCAN_MAX_IMAGES page images in one call.
    No separate schedule call, so visit fields stay null. Stubs make no call at all."""
    n = len(raw_pages)
    sel = list(range(1, min(n, SCAN_MAX_IMAGES) + 1)) if kind == "scan" else []
    source = {"file": pdf.name, "pdf_sha256": digest, "n_pages": n, "kind": kind,
              "text_chars_sent": 0, "scan_pages": sel}
    result = {"source": source, "runs": []}
    if kind == "stub":
        result.update({"card": None, "flags": [f"unreadable stub ({n} pages, no text layer): no protocol features"]})
        return result
    images = render_pages(pdf, sel, run_dir / "pages")
    source["images"] = [str(p) for p in images]
    if dry_run:
        return result
    prompt = (PROMPTS / "trial_card_text.txt").read_text()
    content = [{"type": "text", "text": prompt + "\n\nThis protocol is a scan with no usable text layer. "
                "Below are images of its first " + str(len(sel)) + " pages; Image i is PDF page i. "
                "Cite those page numbers. Fields not shown on these pages are null."}]
    for i, img in enumerate(images):
        content.append({"type": "text", "text": f"Image {i + 1}: PDF page {sel[i]}"})
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(img.read_bytes()).decode()}})
    rec = load_raw(run_dir / "scan.raw.jsonl", model) if reuse else None
    if rec is None:
        client = client or _client()
        rec = call_muse([{"role": "user", "content": content}], run_dir / "scan.raw.jsonl",
                        max_completion_tokens=6000, client=client, model=model)
    text_out = parse_json(rec.pop("content"))
    rec["step"] = "scan"
    result["runs"].append(rec)
    schedule = {"selected": [], "all_schedule_pages": [], "truncated": False}
    card, cites, field_source, flags = merge_card(text_out, None, n, schedule)
    design_checks.apply(card, cites, field_source, flags, text_out, None)
    flags.append(f"scanned protocol: read from images of pages 1-{len(sel)}; visit fields not read")
    result.update({"card": card, "_pages": cites, "_field_source": field_source, "flags": flags})
    _totals(result)
    (run_dir / "card.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read a protocol PDF into a trial card (JSON).")
    ap.add_argument("pdf")
    ap.add_argument("--out", help="write the card JSON here (default: stdout)")
    ap.add_argument("--runs-dir", default=os.environ.get("TRIAL_COPILOT_RUNS_DIR", "cache/runs"),
                    help="where page images and raw API responses go (keep outside the repo)")
    ap.add_argument("--dry-run", action="store_true", help="no API calls: pages, schedule, sizes only")
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--reuse", action="store_true",
                    help="rebuild from saved raw responses in --runs-dir when present (no spend)")
    a = ap.parse_args(argv)
    try:
        res = extract(a.pdf, a.runs_dir, dry_run=a.dry_run, vision=not a.no_vision, reuse=a.reuse)
    except MuseError as e:
        print(f"Muse API error: {e}", file=sys.stderr)
        return 2
    s = json.dumps(res, indent=1, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(s)
    else:
        print(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
