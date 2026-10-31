"""Pre-render the protocol-vs-registry check as static pages (saved results, no API call).

    python3 scripts/export_static.py --out dist/trial-copilot

Writes index.html (the first demo, the myeloma trial) plus one page per other demo, and copies the
stylesheets. Page links point at the official protocol PDFs on ClinicalTrials.gov; no PDF is copied.
Every page carries noindex. The output folder is meant to be served at a sub-path such as
/trial-copilot/, so all links are relative.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from app import cache, mismatch_view, view  # noqa: E402

TEMPLATES = ROOT / "app" / "templates"
STATIC = ROOT / "app" / "static"


def page_name(nct: str, first: str) -> str:
    return "index.html" if nct == first else f"{nct}.html"


def fix_links(html: str, first: str) -> str:
    # demo chips: /?tab=mismatch&demo=NCT... -> NCT....html (or index.html for the lead demo)
    html = re.sub(r'href="/\?tab=mismatch&(?:amp;)?demo=(NCT\d{8})"',
                  lambda m: f'href="{page_name(m.group(1), first)}"', html)
    # the static site has no risk-audit tab
    html = re.sub(r'<p class="small noprint"><a href="/\?tab=audit[^"]*">[^<]*</a></p>\s*', "", html)
    leftover = re.findall(r'(?:href|src)="/(?!/)[^"]*"', html)
    if leftover:
        raise SystemExit(f"absolute app links left in static page: {leftover[:5]}")
    return html


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "trial-copilot"))
    out = Path(ap.parse_args().out)
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    env.globals.update(view.GLOBALS)
    env.filters.update(view.FILTERS)
    data = cache.mismatch()
    if not data:
        raise SystemExit("demo_cache/mismatch.json not found")
    first = data["demos"][0]["nct_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "static").mkdir(exist_ok=True)
    for css in ("style.css", "site.css"):
        shutil.copy(STATIC / css, out / "static" / css)
    tpl = env.get_template("static_site/page.html")
    for d in data["demos"]:
        nct = d["nct_id"]
        mm = mismatch_view.context(data, nct)
        html = tpl.render(mm=mm, t=mm["trial"], base="", intro=nct == first)
        (out / page_name(nct, first)).write_text(fix_links(html, first))
        print("wrote", out / page_name(nct, first))


if __name__ == "__main__":
    main()
