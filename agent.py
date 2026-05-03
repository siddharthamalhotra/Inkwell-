"""
Inkwell — living documentation for any codebase.

Three specialist agents read the repo:
  1. Cartographer — maps the architecture (which files do what, how they connect)
  2. Historian   — reads git log to explain WHY each major piece exists
  3. Translator  — turns it all into docs at three levels: pitch, onboarding, deep

A Synthesis agent consolidates into a Markdown wiki.
MongoDB Atlas stores the docs + embeddings; $rankFusion powers semantic search
("where does auth happen?") over the generated wiki.
"""

import os
import json
import shutil
import threading
import time
import subprocess
import tempfile
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
from mongo_store import (
    save_doc as mongo_save_doc,
    search_docs as mongo_search_docs,
    save_file as mongo_save_file,
    read_file_db, list_files_db, has_repo_snapshot,
    save_git_log as mongo_save_git_log,
    get_git_log_db,
)

load_dotenv()

client = Anthropic()

AGENT_MODEL = "claude-haiku-4-5-20251001"
SYNTHESIS_MODEL = os.environ.get("SYNTHESIS_MODEL", "claude-sonnet-4-6")
MODEL = AGENT_MODEL  # backward compat

# ---------------------------------------------------------------------------
# THREE SPECIALIST SYSTEM PROMPTS
# ---------------------------------------------------------------------------

CARTOGRAPHER_PROMPT = """You are the Cartographer. You map codebases.

Given a repo, you produce a structural map:
  - Top-level architecture (entry points, core modules, peripheral concerns)
  - The dependency shape (which modules import which — top-down)
  - The "spine" of the app: the 3-5 files a new engineer must read to understand it

Use list_files to scan, read_file to inspect. Don't read more than ~10 files —
prioritise breadth over depth. You're drawing the map, not exploring every cave.

Output a structured JSON map at the end:
{
  "architecture_summary": "2-3 sentences",
  "entry_points": [{"path": "...", "why": "..."}],
  "core_modules": [{"path": "...", "purpose": "..."}],
  "spine": ["path1", "path2", "path3"]
}"""

HISTORIAN_PROMPT = """You are the Historian. You explain WHY code exists.

Given a repo, you read git history to surface the story:
  - When were the core modules introduced and by whom (broad strokes)?
  - What was the original intent vs. what they became?
  - What major refactors or pivots can you spot from commit messages?
  - What's the "scar tissue" — code that exists because of past incidents?

Use git_log to read history, read_file to verify current state. Look at the
files the Cartographer marked as "spine" first. Be efficient — make at most
5-6 tool calls total.

Output structured JSON at the end:
{
  "origin_story": "2-3 sentences about how this codebase started",
  "key_moments": [{"approx_when": "...", "what": "...", "why_it_matters": "..."}],
  "scar_tissue": [{"file": "...", "lesson": "..."}]
}"""

SYNTHESIS_PROMPT = """You are the Synthesis agent. You turn raw analysis directly into a polished Markdown wiki.

You receive the Cartographer's structural map and the Historian's narrative. In one pass, you will:

1. Derive a 30-second pitch (one paragraph — what does this codebase DO and for whom?)
2. Write a 5-minute onboarding guide (~400 words — spine files, key concepts, where to look, what NOT to touch yet)
3. Write a deep architectural read (~600 words — why decisions were made, scar tissue, gotchas, extension points)
4. Assemble everything into a single Markdown wiki with these sections in this order:

  # <Repo Name>
  ## TL;DR
  ## Architecture (map formatted as a tree or table)
  ## Onboarding Guide
  ## The Story (origin, key moments, pivots)
  ## Deep Dive
  ## Where to Look For Things (table: concern → file)

Output ONLY the markdown. No JSON, no preamble, no explanation."""


# ---------------------------------------------------------------------------
# Shared tools — all three agents use these
# The last tool is marked for prompt caching so tools + system are cached
# across the multi-turn agent loops.
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list_files",
        "description": "List files in a directory of the cloned repo. Returns relative paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subdir": {"type": "string", "description": "Subdirectory, '' for root"},
                "max_depth": {"type": "integer", "default": 3},
            },
            "required": ["subdir"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file's contents from the cloned repo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within repo"},
                "max_lines": {"type": "integer", "default": 300},
            },
            "required": ["path"],
        },
    },
    {
        "name": "git_log",
        "description": "Get git log for the repo or a specific path. Returns commit messages + dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Specific file/dir, '' for whole repo"},
                "limit": {"type": "integer", "default": 30},
            },
            "required": ["path"],
        },
        "cache_control": {"type": "ephemeral"},  # cache tools array across turns
    },
]


# ---------------------------------------------------------------------------
# Repo cache — avoids re-cloning the same URL within CACHE_TTL seconds
# ---------------------------------------------------------------------------

_CACHE_TTL = 3600  # 1 hour
_repo_cache: dict[str, tuple[Path, float]] = {}
_cache_lock = threading.Lock()

SKIP_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build",
             ".venv", "venv", ".next", "target", ".idea", ".vscode"}


def _clone_repo(github_url: str, token: str | None = None) -> Path:
    """Shallow-clone a repo. Inserts token into URL if provided."""
    tmp = Path(tempfile.mkdtemp(prefix="inkwell_"))
    clone_url = github_url
    if token:
        clone_url = github_url.replace("https://", f"https://{token}@", 1)
    print(f"  cloning {github_url} → {tmp}")
    result = subprocess.run(
        ["git", "clone", "--depth", "20", clone_url, str(tmp)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"git clone failed: {result.stderr}")
    return tmp


def _get_or_clone(github_url: str, token: str | None = None) -> Path:
    """Return a repo dir, reusing a cached clone if fresh."""
    cache_key = f"{github_url}:{token or ''}"
    now = time.time()
    with _cache_lock:
        if cache_key in _repo_cache:
            path, ts = _repo_cache[cache_key]
            if now - ts < _CACHE_TTL and path.exists():
                print(f"  reusing cached clone: {path}")
                return path
            shutil.rmtree(path, ignore_errors=True)
            del _repo_cache[cache_key]
        path = _clone_repo(github_url, token)
        _repo_cache[cache_key] = (path, now)
    return path


# ---------------------------------------------------------------------------
# Per-call tool implementations (closures over repo_dir, no globals)
# ---------------------------------------------------------------------------

def _make_tool_dispatch(repo_dir: Path) -> dict:
    """Return a tool dispatch dict scoped to a specific repo directory."""

    def list_files(subdir: str, max_depth: int = 3) -> list[str]:
        base = repo_dir / subdir if subdir else repo_dir
        if not base.exists():
            return [f"[error] path does not exist: {subdir}"]
        results = []
        base_depth = len(base.parts)
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            depth = len(path.parts) - base_depth
            if depth > max_depth:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            results.append(str(path.relative_to(repo_dir)))
            if len(results) >= 200:
                results.append("... and more (showing first 200)")
                break
        return results

    def read_file(path: str, max_lines: int = 300) -> str:
        full = repo_dir / path
        if not full.exists() or not full.is_file():
            return f"[error] not a file: {path}"
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                lines = []
                for i, line in enumerate(f):
                    if i >= max_lines:
                        lines.append(f"... [truncated at {max_lines} lines]")
                        break
                    lines.append(line.rstrip("\n"))
            return "\n".join(lines)
        except Exception as e:
            return f"[error reading file] {e}"

    def git_log(path: str, limit: int = 30) -> list[dict]:
        cmd = ["git", "log", f"-n{limit}", "--pretty=format:%h|%ai|%an|%s"]
        if path:
            cmd.extend(["--", path])
        result = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
        if result.returncode != 0:
            return [{"error": result.stderr}]
        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0], "date": parts[1],
                    "author": parts[2], "message": parts[3],
                })
        return commits

    return {"list_files": list_files, "read_file": read_file, "git_log": git_log}


# ---------------------------------------------------------------------------
# THE AGENT LOOP
# ---------------------------------------------------------------------------

def run_agent_with_role(
    system_prompt: str,
    user_prompt: str,
    max_turns: int = 15,
    model: str = None,
    max_tokens: int = 4096,
    progress_cb=None,
    tool_dispatch: dict = None,
    stream_output: bool = False,
) -> str:
    """Run ONE specialist agent to completion. Returns its final text output."""
    messages = [{"role": "user", "content": user_prompt}]
    use_model = model or AGENT_MODEL
    dispatch = tool_dispatch or {}
    # Cache the system prompt across multi-turn loops
    sys_cached = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]

    for turn in range(max_turns):
        if stream_output:
            # Stream mode for synthesis — no tools, just text output
            full_text = ""
            with client.messages.stream(
                model=use_model,
                max_tokens=max_tokens,
                system=sys_cached,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_text += text
                    if progress_cb:
                        progress_cb({"type": "wiki_chunk", "chunk": text})
            if progress_cb:
                progress_cb({"type": "agent_done"})
            return full_text

        response = client.messages.create(
            model=use_model,
            max_tokens=max_tokens,
            system=sys_cached,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            if progress_cb:
                progress_cb({"type": "agent_done"})
            return "".join(b.text for b in response.content if b.type == "text")

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if progress_cb:
                    progress_cb({"type": "tool", "tool": block.name, "input": block.input})
                print(f"  → {block.name}({json.dumps(block.input)[:60]}...)")
                func = dispatch.get(block.name)
                if func is None:
                    result = {"error": f"unknown tool: {block.name}"}
                else:
                    try:
                        result = func(**block.input)
                    except Exception as e:
                        result = {"error": str(e)}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result) if not isinstance(result, str) else result,
                })
            messages.append({"role": "user", "content": tool_results})
            continue

        return f"[unexpected stop: {response.stop_reason}]"

    return "[hit max turns]"


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------

def generate_wiki(github_url: str, progress_cb=None, token: str | None = None) -> str:
    """Orchestrate the agents. Cartographer + Historian run in parallel, then Translator, then Synthesis."""
    repo_dir = _get_or_clone(github_url, token)
    dispatch = _make_tool_dispatch(repo_dir)

    from concurrent.futures import ThreadPoolExecutor

    def _cb(agent_name: str):
        if not progress_cb:
            return None
        def cb(event: dict):
            progress_cb({**event, "agent": agent_name})
        return cb

    print("\n=== Cartographer + Historian running in parallel ===")
    if progress_cb:
        progress_cb({"type": "stage", "stage": "cartographer_historian"})

    def run_cartographer():
        return run_agent_with_role(
            CARTOGRAPHER_PROMPT,
            f"Map the architecture of the repo at {github_url}. Start by listing the root.",
            max_turns=8,
            max_tokens=2048,
            progress_cb=_cb("cartographer"),
            tool_dispatch=dispatch,
        )

    def run_historian():
        return run_agent_with_role(
            HISTORIAN_PROMPT,
            f"Read the git history of this repo and tell its story. "
            f"Start by running git_log on the root to see the overall timeline.",
            max_turns=6,
            max_tokens=2048,
            progress_cb=_cb("historian"),
            tool_dispatch=dispatch,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        cart_future = pool.submit(run_cartographer)
        hist_future = pool.submit(run_historian)
        map_output = cart_future.result()
        history_output = hist_future.result()

    map_summary = map_output[-3000:] if len(map_output) > 3000 else map_output
    history_summary = history_output[-3000:] if len(history_output) > 3000 else history_output

    print("\n=== Synthesising into final wiki (Sonnet) ===")
    if progress_cb:
        progress_cb({"type": "stage", "stage": "synthesis"})
    final_md = run_agent_with_role(
        SYNTHESIS_PROMPT,
        f"MAP:\n{map_summary}\n\nHISTORY:\n{history_summary}\n\n"
        f"Produce the final wiki Markdown.",
        max_turns=4,
        model=SYNTHESIS_MODEL,
        max_tokens=8192,
        progress_cb=_cb("synthesis"),
        stream_output=True,
    )

    return final_md


# ---------------------------------------------------------------------------
# Repo snapshot — persists file contents + git log to MongoDB after generation
# ---------------------------------------------------------------------------

def save_repo_snapshot(repo_url: str) -> None:
    """Walk the cached clone and store all text files + git log in MongoDB."""
    repo_dir = _get_cached_repo(repo_url)
    if not repo_dir:
        return
    print(f"  saving repo snapshot to MongoDB: {repo_url}")
    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.stat().st_size > 100_000:  # skip files > 100 KB
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            rel = str(path.relative_to(repo_dir))
            mongo_save_file(repo_url, rel, content)
        except Exception:
            pass
    # Git log
    result = subprocess.run(
        ["git", "log", "-n100", "--pretty=format:%h|%ai|%an|%s"],
        cwd=repo_dir, capture_output=True, text=True,
    )
    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({"hash": parts[0], "date": parts[1],
                            "author": parts[2], "message": parts[3]})
    mongo_save_git_log(repo_url, commits)
    print(f"  snapshot saved ({len(commits)} commits)")


# ---------------------------------------------------------------------------
# MongoDB-backed tool dispatch — used by chat when snapshot exists
# ---------------------------------------------------------------------------

def _make_mongo_tool_dispatch(repo_url: str) -> dict:
    """Tools that read from MongoDB instead of the local filesystem."""

    def list_files(subdir: str, max_depth: int = 3) -> list[str]:
        all_paths = list_files_db(repo_url, subdir)
        prefix_depth = len(subdir.split("/")) if subdir else 0
        results = []
        for p in sorted(all_paths):
            depth = len(p.split("/")) - 1 - prefix_depth
            if depth <= max_depth:
                results.append(p)
            if len(results) >= 200:
                results.append("... and more (showing first 200)")
                break
        return results

    def read_file(path: str, max_lines: int = 300) -> str:
        content = read_file_db(repo_url, path)
        if content is None:
            return f"[error] file not found in snapshot: {path}"
        lines = content.split("\n")
        if len(lines) > max_lines:
            return "\n".join(lines[:max_lines]) + f"\n... [truncated at {max_lines} lines]"
        return content

    def git_log(path: str, limit: int = 30) -> list[dict]:
        commits = get_git_log_db(repo_url, limit=100)
        if path:
            # approximate path filtering — git log -- path not available from DB
            commits = [c for c in commits if path.split("/")[-1] in c.get("message", "")]
        return commits[:limit]

    return {"list_files": list_files, "read_file": read_file, "git_log": git_log}


# ---------------------------------------------------------------------------
# Chat — agentic Q&A with persistent tool access and conversation memory
# ---------------------------------------------------------------------------

CHAT_SYSTEM = """You are a senior engineer reviewing this codebase with a collaborator.
You have three resources:
  1. Wiki sections — architecture summary, design decisions, origin story
  2. Raw source files — the actual code, via read_file and list_files
  3. Git history — the commit log, via git_log

How to reason:
  - Start from the wiki context provided for each question.
  - Use the tools to read actual source when you need to verify, go deeper, or find something not in the wiki.
  - Don't just describe what the code does — reason about WHY it was written that way,
    whether it achieves its intent, and where the logic holds or breaks down.
  - If the code contradicts the wiki or contradicts sound programming practice, say so explicitly.
  - Build on the conversation history: refer back to earlier findings, update your model as you learn more.
  - Cite file paths and line context. Be direct."""


def _get_cached_repo(github_url: str) -> Path | None:
    """Return the in-memory cached clone path if still valid."""
    now = time.time()
    with _cache_lock:
        for key, (path, ts) in _repo_cache.items():
            if key.startswith(github_url) and now - ts < _CACHE_TTL and path.exists():
                return path
    return None


def answer_question(
    question: str,
    context: str,
    repo_url: str | None = None,
    history: list[dict] | None = None,
) -> str:
    """Agentic chat with persistent MongoDB tool access and conversation history.

    history: prior turns as [{role: 'user'|'assistant', content: str}].
    """
    # Prefer MongoDB snapshot (persistent) over local clone (ephemeral)
    if repo_url and has_repo_snapshot(repo_url):
        dispatch = _make_mongo_tool_dispatch(repo_url)
        tools = TOOLS
    elif repo_url and _get_cached_repo(repo_url):
        dispatch = _make_tool_dispatch(_get_cached_repo(repo_url))
        tools = TOOLS
    else:
        dispatch, tools = {}, []

    sys_prompt = [{"type": "text", "text": CHAT_SYSTEM, "cache_control": {"type": "ephemeral"}}]

    # Thread in conversation history (plain text turns only — no tool-call blocks)
    messages: list[dict] = [
        {"role": m["role"], "content": m["content"]}
        for m in (history or [])
    ]
    # Current question with fresh wiki context
    messages.append({
        "role": "user",
        "content": f"Wiki context (most relevant sections):\n{context}\n\nQuestion: {question}",
    })

    for _ in range(10):
        kwargs: dict = dict(
            model=SYNTHESIS_MODEL,
            max_tokens=2048,
            system=sys_prompt,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools

        response = client.messages.create(**kwargs)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return "".join(b.text for b in response.content if b.type == "text")

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                func = dispatch.get(block.name)
                try:
                    result = func(**block.input) if func else {"error": "tool not available"}
                except Exception as e:
                    result = {"error": str(e)}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result) if not isinstance(result, str) else result,
                })
            messages.append({"role": "user", "content": tool_results})
            continue

        break

    return "".join(b.text for b in messages[-1]["content"] if hasattr(b, "text"))


# ---------------------------------------------------------------------------
# MongoDB persistence — wired to mongo_store.py
# ---------------------------------------------------------------------------

def save_doc(repo_url: str, section: str, text: str) -> None:
    mongo_save_doc(repo_url, section, text)


def search_docs(repo_url: str, query: str, limit: int = 5) -> list[dict]:
    return mongo_search_docs(repo_url, query, limit)


# ---------------------------------------------------------------------------
# Run all three agents end-to-end
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import re
    repo_url = (
        sys.argv[1] if len(sys.argv) > 1
        else os.environ.get("TARGET_REPO", "https://github.com/illiaputintsev/plantsvszombies.git")
    )

    wiki = generate_wiki(repo_url)

    print("\n" + "="*60)
    print("FINAL WIKI:")
    print("="*60)
    print(wiki)

    with open("output_wiki.md", "w", encoding="utf-8") as f:
        f.write(wiki)
    print("\nSaved to output_wiki.md")

    print("\nSaving wiki sections to MongoDB...")
    sections = re.split(r'\n(?=## )', wiki)
    for section in sections:
        heading = section.split('\n', 1)[0].strip('# ').strip()
        if not heading:
            heading = "Introduction"
        save_doc(repo_url, heading, section.strip())
        print(f"  saved: {heading}")
    print("Done — searchable via mongo_store.search_docs()")
