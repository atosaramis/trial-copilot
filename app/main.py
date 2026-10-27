"""Web app (build spec section 2): Tab 1 protocol audit, Tab 2 validation.

FastAPI + Jinja2 + HTMX, with server-sent events streaming each audit section as it is ready.
Demo trials replay saved results (no API call). "Re-run live on Meta API" runs the real pipeline
when live mode is on (TRIAL_COPILOT_LIVE=1 and META_API_KEY set), with a per-visitor limit and a
daily dollar cap.

Run locally:  uvicorn app.main:app --port 8000
Environment:  TRIAL_COPILOT_POOLS (registry pools dir, default data/pools)
              TRIAL_COPILOT_PDF_DIR (optional local folder of <NCT>.pdf; otherwise demo PDFs are
              fetched from ClinicalTrials.gov at run time into cache/)
              TRIAL_COPILOT_LIVE=1, TRIAL_COPILOT_DAILY_CAP_USD (default 3), TRIAL_COPILOT_STEP_DELAY_S
"""
from __future__ import annotations

import datetime as dt
import json
import os
import queue
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import cache, view

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache"
POOLS = Path(os.environ.get("TRIAL_COPILOT_POOLS", ROOT / "data" / "pools"))
PDF_DIR = os.environ.get("TRIAL_COPILOT_PDF_DIR")
STEP_DELAY = float(os.environ.get("TRIAL_COPILOT_STEP_DELAY_S", "0.35"))
DAILY_CAP = float(os.environ.get("TRIAL_COPILOT_DAILY_CAP_USD", "3"))
LIVE_RUN_ESTIMATE = 0.30  # USD, standard rate: extraction ~0.05-0.18, search ~0.01, memo ~0.05
VISITOR_GAP_S = 600

env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                  autoescape=select_autoescape(["html"]))
env.globals.update(view.GLOBALS)
env.filters.update(view.FILTERS)

app = FastAPI(title="Trial Feasibility Copilot")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

JOBS: dict[str, queue.Queue] = {}
_last_live: dict[str, float] = {}
_lock = threading.Lock()


def live_status() -> dict:
    on = os.environ.get("TRIAL_COPILOT_LIVE") == "1" and bool(os.environ.get("META_API_KEY"))
    spent = _spent_today()
    return {"enabled": on, "spent_today": round(spent, 2), "cap": DAILY_CAP,
            "room": on and spent + LIVE_RUN_ESTIMATE <= DAILY_CAP}


def _ledger() -> Path:
    return CACHE / "live_spend.json"


def _spent_today() -> float:
    try:
        return json.loads(_ledger().read_text()).get(dt.date.today().isoformat(), 0.0)
    except (OSError, ValueError):
        return 0.0


def _add_spend(usd: float):
    with _lock:
        CACHE.mkdir(exist_ok=True)
        d = {}
        if _ledger().exists():
            d = json.loads(_ledger().read_text())
        k = dt.date.today().isoformat()
        d[k] = round(d.get(k, 0.0) + usd, 6)
        _ledger().write_text(json.dumps(d))


def render(name: str, **ctx) -> str:
    return env.get_template(name).render(**ctx)


# ----------------------------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def index(demo: str | None = None, tab: str = "audit"):
    d = cache.demos().get(demo) if demo else None
    full = view.full_context(d) if d else None
    return render("index.html", demos=cache.demos(), live=live_status(), tab=tab, full=full)


@app.post("/start", response_class=HTMLResponse)
async def start(request: Request, demo: str = Form(""), mode: str = Form("saved"),
                pdf: UploadFile | None = File(None)):
    """Start an audit and return the skeleton; sections arrive over /events/<job>."""
    d, pdf_path, sha = None, None, None
    if pdf is not None and pdf.filename:
        data = await pdf.read()
        if not data.startswith(b"%PDF"):
            return HTMLResponse(render("notice.html", kind="error", text="That file is not a PDF."))
        sha = cache.sha256_bytes(data)
        (CACHE / "uploads").mkdir(parents=True, exist_ok=True)
        pdf_path = CACHE / "uploads" / f"{sha}.pdf"
        pdf_path.write_bytes(data)
        d = cache.demo_by_sha(sha)
    elif demo:
        d = cache.demos().get(demo)
        if d is None:
            raise HTTPException(404, "unknown demo")
        sha = d["pdf_sha256"]
    else:
        return HTMLResponse(render("notice.html", kind="error", text="Choose a demo trial or upload a protocol PDF."))

    job = uuid.uuid4().hex[:12]
    q: queue.Queue = queue.Queue()
    JOBS[job] = q
    if d is not None and mode != "live":
        threading.Thread(target=_replay, args=(d, q), daemon=True).start()
        source = {"kind": "saved", "sha": sha, "nct": d["nct_id"]}
    else:
        live = live_status()
        visitor = request.client.host if request.client else "?"
        why = None
        if not live["enabled"]:
            why = ("Live mode is off on this server. The 5 demo trials replay saved results; set "
                   "TRIAL_COPILOT_LIVE=1 and META_API_KEY to run new protocols.")
        elif not live["room"]:
            why = f"Today's live-run budget (${DAILY_CAP:.2f}) is used up. Saved demos still work."
        elif time.time() - _last_live.get(visitor, 0) < VISITOR_GAP_S:
            why = "One live run per visitor every 10 minutes. Saved demos still work."
        if why:
            JOBS.pop(job, None)
            return HTMLResponse(render("notice.html", kind="info", text=why))
        _last_live[visitor] = time.time()
        if pdf_path is None:
            pdf_path = _demo_pdf(d)
        nct = d["nct_id"] if d else None
        threading.Thread(target=_live, args=(pdf_path, nct, d, q), daemon=True).start()
        source = {"kind": "live", "sha": sha, "nct": nct}
    return HTMLResponse(render("audit.html", job=job, source=source, demo=d, ctx=None))


@app.get("/events/{job}")
def events(job: str):
    q = JOBS.get(job)
    if q is None:
        raise HTTPException(404)

    def gen():
        while True:
            try:
                ev = q.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            yield "data: " + json.dumps(ev) + "\n\n"
            if ev.get("done"):
                JOBS.pop(job, None)
                return

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/reveal/{nct}", response_class=HTMLResponse)
def reveal(nct: str):
    r = cache.reveal(nct)
    if r is None:
        raise HTTPException(404)
    return render("reveal_open.html", r=r, nct=nct)


@app.get("/page/{sha}/{n}.png")
def page_png(sha: str, n: int):
    """A protocol page image, rendered at run time into cache/ (never stored in the repo)."""
    if not sha.isalnum() or not 1 <= n <= 2000:
        raise HTTPException(400)
    out = CACHE / "pages" / sha / f"{n}.png"
    if not out.exists():
        pdf = _pdf_for_sha(sha)
        if pdf is None:
            raise HTTPException(404, "protocol PDF not available on this server")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["pdftoppm", "-png", "-r", "110", "-f", str(n), "-l", str(n), "-singlefile",
                        str(pdf), str(out.with_suffix(""))], capture_output=True, timeout=60)
    if not out.exists():
        raise HTTPException(404)
    return FileResponse(out, media_type="image/png")


@app.get("/pdf/{sha}")
def pdf_file(sha: str):
    p = _pdf_for_sha(sha) if sha.isalnum() else None
    if p is None:
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf")


# ------------------------------------------------------------------------------ helpers
def _pdf_for_sha(sha: str) -> Path | None:
    up = CACHE / "uploads" / f"{sha}.pdf"
    if up.exists():
        return up
    d = cache.demo_by_sha(sha)
    return _demo_pdf(d) if d else None


def _demo_pdf(d: dict) -> Path | None:
    if PDF_DIR and (Path(PDF_DIR) / f"{d['nct_id']}.pdf").exists():
        return Path(PDF_DIR) / f"{d['nct_id']}.pdf"
    p = CACHE / "pdfs" / f"{d['pdf_sha256']}.pdf"
    if not p.exists():
        try:
            r = httpx.get(d["protocol_url"], timeout=60, follow_redirects=True)
            r.raise_for_status()
        except httpx.HTTPError:
            return None
        if cache.sha256_bytes(r.content) != d["pdf_sha256"]:
            return None
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
    return p


def _put(q, target, html, mode="replace", **kw):
    q.put({"target": target, "mode": mode, "html": html, **kw})


def _replay(d: dict, q: queue.Queue):
    """Stream a saved demo in the same order as a live run (about 2-3 seconds)."""
    ctx = view.full_context(d)
    _put(q, "card", render("card.html", c=ctx))
    time.sleep(STEP_DELAY)
    for st in ctx["steps"]:
        _put(q, "trace-steps", render("trace_step.html", st=st), mode="append")
        time.sleep(STEP_DELAY)
    _put(q, "trace-summary", render("trace_summary.html", c=ctx))
    _put(q, "risk", render("risk.html", c=ctx))
    time.sleep(STEP_DELAY)
    _put(q, "memo", render("memo.html", c=ctx))
    _put(q, "reveal", render("reveal_sealed.html", c=ctx), done=True)


def _live(pdf_path: Path | None, nct: str | None, d: dict | None, q: queue.Queue):
    from .audit import search_and_risk
    from .extract import extract
    from .memo import write_memo
    spent = 0.0
    try:
        if pdf_path is None:
            raise RuntimeError("the protocol PDF could not be fetched")
        _put(q, "card", render("notice.html", kind="info", text="Reading the protocol with Muse Spark 1.3 "
                                                                   "(text, then the visit-schedule pages)..."))
        ex = extract(pdf_path, runs_dir=CACHE / "runs")
        spent += ex["totals"]["cost_usd"]
        base = {"nct_id": nct, "label": (d or {}).get("label", "Uploaded protocol"),
                "registry_title_2017": (d or {}).get("registry_title_2017"),
                "pdf_sha256": ex["source"]["pdf_sha256"], "pdf_pages": ex["source"]["n_pages"],
                "protocol_url": (d or {}).get("protocol_url"),
                "card": {"card": ex["card"], "_pages": ex["_pages"], "flags": ex["flags"]}}
        ctx = view.full_context(base)
        _put(q, "card", render("card.html", c=ctx))

        def on_step(st):
            _put(q, "trace-steps", render("trace_step.html", st=view.step_view(st)), mode="append")

        audit = search_and_risk(ex["card"], nct, POOLS, on_step=on_step)
        spent += audit["search"].get("cost_usd") or 0.0
        base["audit"] = audit
        ctx = view.full_context(base)
        _put(q, "trace-summary", render("trace_summary.html", c=ctx))
        _put(q, "risk", render("risk.html", c=ctx))
        _put(q, "memo", render("notice.html", kind="info", text="Muse Wonder is writing the memo; code will check it..."))
        m = write_memo(ex["card"], audit, POOLS, nct, ex["_pages"], ex["flags"])
        spent += m["cost_usd"]
        base["memo"] = {k: m[k] for k in ("memo", "check", "model", "reasoning_effort", "usage", "cost_usd", "latency_s")}
        ctx = view.full_context(base)
        _put(q, "memo", render("memo.html", c=ctx))
        _put(q, "reveal", render("reveal_sealed.html", c=ctx) if nct in cache.demos() else "",
             done=True)
    except Exception as e:  # noqa: BLE001 - shown to the user, full trace in the server log
        traceback.print_exc()
        _put(q, "memo", render("notice.html", kind="error", text=f"Live run stopped: {type(e).__name__}: {str(e)[:300]}"),
             done=True)
    finally:
        _add_spend(spent)
