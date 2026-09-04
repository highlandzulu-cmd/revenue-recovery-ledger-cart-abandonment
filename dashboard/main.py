"""Custom ops dashboard for the failed-payment recovery agent - replaces the
Streamlit prototype with a page matching the rest of the project's visual
identity (the same ledger/audit-trail language as storefront/admin and the
Recovery Ledger explainer), so the whole system reads as one product.

Run with:
    uvicorn dashboard.main:app --reload --port 8502
"""
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.pipeline import confidence_calibration, summarize

BASE_DIR = Path(__file__).parent
RESULTS_PATH = BASE_DIR.parent / "data" / "results.json"

# The two agents are one system (see README's "The two agents" section) - this
# is what lets each app link to the other instead of reading as unrelated
# projects. Defaults to local dev ports; set STOREFRONT_URL once both are
# deployed so the link keeps working there too.
STOREFRONT_URL = os.environ.get("STOREFRONT_URL", "http://localhost:8000")

app = FastAPI(title="Recovery Agent Dashboard")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _load():
    if not RESULTS_PATH.exists():
        return None, None
    results = json.loads(RESULTS_PATH.read_text())
    return results, summarize(results)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    results, stats = _load()
    if results is None:
        return templates.TemplateResponse(request, "empty.html", {})

    root_cause_counts = _count(results, "root_cause")
    action_counts = _count(results, "final_action")

    diagnosis_disagreements = [r for r in results if not r["root_cause_agree"]]
    reply_disagreements = [
        r for r in results if r["reply_ai_intent"] and not r["baseline_ai_agree"]
    ]
    guardrail_hits = [r for r in results if r["guardrail_overridden"]]
    promised = [r for r in results if r["promise_resolution"]]
    replies = [r for r in results if r["reply_ai_intent"]]

    return templates.TemplateResponse(request, "index.html", {
        "stats": stats,
        "results": results,
        "root_cause_counts": root_cause_counts,
        "action_counts": action_counts,
        "diagnosis_disagreements": diagnosis_disagreements,
        "reply_disagreements": reply_disagreements,
        "guardrail_hits": guardrail_hits,
        "promised": promised,
        "replies": replies,
        "calibration_buckets": confidence_calibration(results),
        "storefront_url": STOREFRONT_URL,
    })


@app.get("/connect", response_class=HTMLResponse)
def connect(request: Request):
    """Scripted 'merchant onboarding' demo: shows the actual pitch (a merchant
    only ever has to hand over one Razorpay key) as a real, watchable flow instead
    of a slide. Reads the same results.json the dashboard itself reads, so the
    numbers it reveals mid-flow are real, not invented for the demo."""
    results, stats = _load()
    if results is None:
        return templates.TemplateResponse(request, "empty.html", {})
    return templates.TemplateResponse(request, "onboarding.html", {"stats": stats})


def _count(results: list[dict], field: str) -> list[tuple]:
    counts: dict[str, int] = {}
    for r in results:
        v = r.get(field) or "none"
        counts[v] = counts.get(v, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    top = ordered[0][1] if ordered else 1
    return [(name, n, round(100 * n / top)) for name, n in ordered]


@app.post("/rerun")
def rerun(mode: str = Form("mock")):
    """Re-run the batch from the dashboard instead of the CLI. mode is 'mock'
    (instant, no API key) or 'groq' (live reasoning, paced ~5.5s/case)."""
    from agent import mock_llm
    from agent.pipeline import run_batch

    if mode == "groq":
        from agent import llm_groq, reply_interpreter_groq
        run_batch(
            llm_groq.diagnose_and_decide,
            pace_seconds=llm_groq.PACING_SECONDS,
            interpret_reply_fn=reply_interpreter_groq.interpret,
        )
    else:
        run_batch(mock_llm.diagnose_and_decide)

    return RedirectResponse(url="/", status_code=303)
