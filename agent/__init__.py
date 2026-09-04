"""Loads .env once, for every entrypoint that touches this package (agent.pipeline's
CLI, dashboard/main.py, storefront/main.py) - so GROQ_API_KEY, RAZORPAY_KEY_ID/SECRET
etc. are available from a plain `uvicorn ...` or `python -m agent.pipeline` regardless
of whether the calling shell happened to have them exported already.

python-dotenv has been a listed dependency since the start of this project but nothing
ever actually called load_dotenv() - every os.environ[...] / Groq() lookup depended on
the launching shell already having the keys exported. That's fragile (a fresh shell,
a background process, a restarted server all silently lose them) and it's exactly what
was happening here: a live Groq batch ran for 10+ minutes with no key in its
environment, quietly falling back to the deterministic baseline on every case instead
of erroring loudly.
"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
