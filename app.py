"""Inkwell web demo — Flask app with SSE progress streaming."""
import json
import queue
import re
import threading
from flask import Flask, Response, jsonify, request, send_from_directory
from dotenv import load_dotenv
load_dotenv()

import agent as ag

app = Flask(__name__, static_folder=".")
_last_repo_url: str | None = None

_GITHUB_RE = re.compile(
    r"(https?://github\.com/[^/]+/[^/#?]+?)(?:\.git)?(?:/.*)?$"
)

def normalize_github_url(raw: str) -> str | None:
    """Return the canonical clone URL or None if it doesn't look like a GitHub repo."""
    m = _GITHUB_RE.match(raw.strip())
    return m.group(1) if m else None


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.get("/")
def index():
    return send_from_directory(".", "index.html")


@app.get("/generate")
def generate():
    raw_url = request.args.get("url", "").strip()
    repo_url = normalize_github_url(raw_url)
    if not repo_url:
        return jsonify(error="Paste a GitHub repo URL, e.g. https://github.com/owner/repo"), 400

    event_q: queue.Queue = queue.Queue()

    def worker():
        global _last_repo_url
        try:
            def progress_cb(event: dict):
                event_q.put(event)

            wiki = ag.generate_wiki(repo_url, progress_cb=progress_cb)
            _last_repo_url = repo_url

            try:
                sections = re.split(r"\n(?=## )", wiki)
                for section in sections:
                    heading = section.split("\n", 1)[0].strip("# ").strip() or "Introduction"
                    ag.save_doc(repo_url, heading, section.strip())
            except Exception:
                pass  # MongoDB save is best-effort; don't crash the demo

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
    repo_url = data.get("repo_url") or _last_repo_url
    query = data.get("query", "").strip()
    if not repo_url or not query:
        return jsonify(error="Missing repo_url or query"), 400
    try:
        results = ag.search_docs(repo_url, query)
        return jsonify(results=results)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


if __name__ == "__main__":
    app.run(debug=False, port=5001, threaded=True)
