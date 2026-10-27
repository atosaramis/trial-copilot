"""No protocol PDFs, keys or .env files in the repo."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_PATTERNS = [re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), re.compile(r"LLM\|\d+\|[A-Za-z0-9_-]{8,}"),
                re.compile(r"META_API_KEY\s*=\s*['\"]?[A-Za-z0-9|_-]{8,}")]


def _tracked_and_untracked():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / f for f in out.splitlines() if f]


def test_no_pdfs_or_env_files():
    bad = [p.name for p in _tracked_and_untracked()
           if p.suffix.lower() == ".pdf" or p.name.startswith(".env")]
    assert not bad, bad


def test_no_api_keys():
    hits = []
    for p in _tracked_and_untracked():
        if p.is_file() and p.stat().st_size < 2_000_000:
            t = p.read_text(errors="replace")
            for rx in KEY_PATTERNS:
                if rx.search(t):
                    hits.append(p.name)
    assert not hits, hits


def test_no_cohort_data_pools_or_prep_scripts():
    """The study cohort (with its later outcomes), the registry pools, protocol text and the
    prep scripts stay outside the repo."""
    bad = []
    for p in _tracked_and_untracked():
        rel = p.relative_to(ROOT).as_posix()
        if (p.suffix.lower() in (".parquet", ".gz", ".jsonl")
                or p.name.startswith("cohort_1436")
                or rel.startswith(("prep/", "data/pools/", "protocols/"))
                or (p.suffix == ".txt" and not rel.startswith("app/prompts/") and p.name != "requirements.txt")):
            bad.append(rel)
    assert not bad, bad


def test_no_later_outcome_columns_in_code_paths_the_search_uses():
    for f in ("app/tools.py", "app/agent.py", "app/risk.py", "app/audit.py"):
        src = (ROOT / f).read_text()
        assert "status_2020" not in src.replace('"status_2020"', ""), f
        assert "cohort_1436.csv" not in src, f
