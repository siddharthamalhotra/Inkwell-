"""Inkwell web demo — Flask app with SSE progress streaming."""
import hashlib
import hmac as _hmac
import json
import os
import queue
import re
import threading
import time
from collections import defaultdict
from flask import Flask, Response, jsonify, request, send_from_directory
from dotenv import load_dotenv
load_dotenv()

import agent as ag

_WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

app = Flask(__name__, static_folder=".")

_GITHUB_RE = re.compile(
    r"(https?://github\.com/[^/]+/[^/#?]+?)(?:\.git)?(?:/.*)?$"
)

# ---------------------------------------------------------------------------
# Rate limiting — 5 generations per IP per hour
# ---------------------------------------------------------------------------

_RATE_LIMIT  = 5
_RATE_WINDOW = 3600  # seconds

_rate_lock  = threading.Lock()
_rate_store: dict[str, list[float]] = defaultdict(list)


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        times = [t for t in _rate_store[ip] if now - t < _RATE_WINDOW]
        _rate_store[ip] = times
        if len(times) >= _RATE_LIMIT:
            return True
        _rate_store[ip].append(now)
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_github_url(raw: str) -> str | None:
    m = _GITHUB_RE.match(raw.strip())
    return m.group(1) if m else None


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(".", "index.html")


@app.get("/generate")
def generate():
    raw_url = request.args.get("url", "").strip()
    repo_url = normalize_github_url(raw_url)
    if not repo_url:
        return jsonify(error="Paste a GitHub repo URL, e.g. https://github.com/owner/repo"), 400

    token = request.args.get("token", "").strip() or None

    ip = request.remote_addr or "unknown"
    if _is_rate_limited(ip):
        def _rate_err():
            yield _sse({"type": "error", "message": "Rate limit reached: max 5 wikis per hour per IP."})
        return Response(_rate_err(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    event_q: queue.Queue = queue.Queue()

    def worker():
        try:
            def progress_cb(event: dict):
                event_q.put(event)

            wiki = ag.generate_wiki(repo_url, progress_cb=progress_cb, token=token)

            try:
                sections = re.split(r"\n(?=## )", wiki)
                for section in sections:
                    heading = section.split("\n", 1)[0].strip("# ").strip() or "Introduction"
                    ag.save_doc(repo_url, heading, section.strip())
            except Exception:
                pass  # MongoDB save is best-effort; don't crash the demo

            # Save file contents + git log to MongoDB in background so chat
            # tools have persistent access to the codebase.
            threading.Thread(
                target=ag.save_repo_snapshot, args=(repo_url,), daemon=True
            ).start()

            event_q.put({"type": "wiki", "content": wiki, "repo_url": repo_url})
        except Exception as exc:
            event_q.put({"type": "error", "message": str(exc)})

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            try:
                event = event_q.get(timeout=300)
            except queue.Empty:
                yield _sse({"type": "heartbeat"})
                continue
            yield _sse(event)
            if event.get("type") in ("wiki", "error"):
                break

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/search")
def search():
    data = request.get_json(force=True)
    repo_url = data.get("repo_url", "").strip()
    query = data.get("query", "").strip()
    if not repo_url or not query:
        return jsonify(error="Missing repo_url or query"), 400
    try:
        results = ag.search_docs(repo_url, query)
        return jsonify(results=results)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.post("/chat")
def chat():
    data = request.get_json(force=True)
    repo_url = data.get("repo_url", "").strip()
    question = data.get("question", "").strip()
    history  = data.get("history", [])  # [{role, content}] from prior turns
    if not repo_url or not question:
        return jsonify(error="Missing repo_url or question"), 400
    try:
        results = ag.search_docs(repo_url, question, limit=4)
        if results:
            context = "\n\n".join(f"[{r['section']}]\n{r['text']}" for r in results)
            sources = [r["section"] for r in results]
        else:
            context = ""
            sources = []
        answer = ag.answer_question(question, context, repo_url=repo_url, history=history)
        return jsonify(answer=answer, sources=sources)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


@app.post("/webhook")
def webhook():
    """GitHub push webhook — regenerates wiki when a significant commit lands."""
    if _WEBHOOK_SECRET:
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + _hmac.new(
            _WEBHOOK_SECRET.encode(), request.data, hashlib.sha256
        ).hexdigest()
        if not _hmac.compare_digest(sig, expected):
            return jsonify(error="invalid signature"), 401

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return jsonify(status="ok"), 200
    if event != "push":
        return jsonify(status="ignored", reason=f"event={event}"), 200

    payload = request.get_json(force=True) or {}
    raw_url = (payload.get("repository") or {}).get("html_url", "")
    repo_url = normalize_github_url(raw_url)
    if not repo_url:
        return jsonify(error="could not parse repo URL"), 400

    significant, reason = ag.is_significant_push(payload)
    if not significant:
        return jsonify(status="skipped", reason=reason), 200

    def _regen():
        try:
            wiki = ag.generate_wiki(repo_url)
            sections = re.split(r"\n(?=## )", wiki)
            for section in sections:
                heading = section.split("\n", 1)[0].strip("# ").strip() or "Introduction"
                ag.save_doc(repo_url, heading, section.strip())
            ag.save_repo_snapshot(repo_url)
            print(f"  webhook regen complete: {repo_url}")
        except Exception as exc:
            print(f"  webhook regen failed: {exc}")

    threading.Thread(target=_regen, daemon=True).start()
    return jsonify(status="regenerating", reason=reason), 202


if __name__ == "__main__":
    app.run(debug=False, port=5001, threaded=True)
