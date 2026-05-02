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
import time
import subprocess
import tempfile
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
from mongo_store import save_doc as mongo_save_doc, search_docs as mongo_search_docs

load_dotenv()

client = Anthropic()

# Use cheap fast model for the agents (lots of tool calls, big rate-limit headroom)
# Use Sonnet for synthesis only — it's the polished final output judges see.
AGENT_MODEL = "claude-haiku-4-5-20251001"
SYNTHESIS_MODEL = os.environ.get("SYNTHESIS_MODEL", "claude-sonnet-4-6")
MODEL = AGENT_MODEL  # backward compat

# ---------------------------------------------------------------------------
# THREE SPECIALIST SYSTEM PROMPTS — this is where Inkwell's "wow" lives.
# Each agent has the SAME tools but a different lens.
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

TRANSLATOR_PROMPT = """You are the Translator. You write docs for three audiences.

Given the Cartographer's map and the Historian's narrative, you produce three docs:
  1. The 30-second pitch (one paragraph — what does this codebase DO and for whom?)
  2. The 5-minute onboarding (a new dev's first read — covers the spine, key concepts,
     where to look for what, what NOT to touch yet)
  3. The deep architectural read (for someone modifying core systems — covers why
     decisions were made, scar tissue, gotchas, extension points)

Read sparingly. You have the map and the history already; only fetch a file if
you need to verify a specific claim or grab a code example. Make at most 3 tool calls.

Output structured JSON at the end:
{
  "pitch": "...",
  "onboarding_md": "full markdown, ~400 words with headings",
  "deep_md": "full markdown, ~600 words with headings"
}"""

SYNTHESIS_PROMPT = """You combine three agent outputs into a single Markdown wiki.

You receive: the Cartographer's map, the Historian's narrative, and the Translator's
three-level docs. Produce a single beautiful README.md style document with these
sections, in this order:
  # <Repo Name>
  ## TL;DR (the pitch)
  ## Architecture (the map, formatted as a tree)
  ## Onboarding Guide (the onboarding doc)
  ## The Story (the history)
  ## Deep Dive (the deep doc)
  ## Where to Look For Things (a table mapping concerns -> files)

Output ONLY the markdown. No JSON, no preamble."""


# ---------------------------------------------------------------------------
# Shared tools — all three agents use these
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
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

# Set by clone_repo() before running agents — the local path to the cloned repo
REPO_DIR: Path | None = None

SKIP_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build",
             ".venv", "venv", ".next", "target", ".idea", ".vscode"}


def clone_repo(github_url: str) -> Path:
    """Shallow clone a public repo to a tempdir. Returns the path."""
    global REPO_DIR
    tmp = Path(tempfile.mkdtemp(prefix="inkwell_"))
    print(f"  cloning {github_url} → {tmp}")
    result = subprocess.run(
        ["git", "clone", "--depth", "50", github_url, str(tmp)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr}")
    REPO_DIR = tmp
    return tmp


def list_files(subdir: str, max_depth: int = 3) -> list[str]:
    """Walk REPO_DIR/subdir, return relative paths up to max_depth, capped at 200."""
    if REPO_DIR is None:
        return ["[error] no repo cloned yet"]
    base = REPO_DIR / subdir if subdir else REPO_DIR
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
        results.append(str(path.relative_to(REPO_DIR)))
        if len(results) >= 200:
            results.append("... and more (showing first 200)")
            break
    return results


def read_file(path: str, max_lines: int = 300) -> str:
    """Read REPO_DIR/path, return first max_lines lines."""
    if REPO_DIR is None:
        return "[error] no repo cloned yet"
    full = REPO_DIR / path
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
    """Return git log for the repo or a specific path."""
    if REPO_DIR is None:
        return [{"error": "no repo cloned yet"}]
    cmd = ["git", "log", f"-n{limit}", "--pretty=format:%h|%ai|%an|%s"]
    if path:
        cmd.extend(["--", path])
    result = subprocess.run(cmd, cwd=REPO_DIR, capture_output=True, text=True)
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


TOOL_DISPATCH = {
    "list_files": list_files,
    "read_file": read_file,
    "git_log": git_log,
}


# ---------------------------------------------------------------------------
# THE AGENT LOOP
# ---------------------------------------------------------------------------

def run_agent_with_role(system_prompt: str, user_prompt: str,
                        max_turns: int = 15, model: str = None,
                        max_tokens: int = 4096,
                        progress_cb=None) -> str:
    """Runs ONE specialist agent to completion. Returns its final text output."""
    messages = [{"role": "user", "content": user_prompt}]
    use_model = model or AGENT_MODEL

    for turn in range(max_turns):
        response = client.messages.create(
            model=use_model,
            max_tokens=max_tokens,
            system=system_prompt,
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
                func = TOOL_DISPATCH[block.name]
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

def generate_wiki(github_url: str, progress_cb=None) -> str:
    """Orchestrates the agents. Cartographer + Historian run in parallel, then Translator, then Synthesis."""
    global REPO_DIR
    REPO_DIR = clone_repo(github_url)

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
            progress_cb=_cb("cartographer"),
        )

    def run_historian():
        return run_agent_with_role(
            HISTORIAN_PROMPT,
            f"Read the git history of this repo and tell its story. "
            f"Start by running git_log on the root to see the overall timeline.",
            max_turns=6,
            progress_cb=_cb("historian"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        cart_future = pool.submit(run_cartographer)
        hist_future = pool.submit(run_historian)
        map_output = cart_future.result()
        history_output = hist_future.result()

    map_summary = map_output[-3000:] if len(map_output) > 3000 else map_output
    history_summary = history_output[-3000:] if len(history_output) > 3000 else history_output

    print("\n=== Translator writing docs for three audiences ===")
    if progress_cb:
        progress_cb({"type": "stage", "stage": "translator"})
    docs_output = run_agent_with_role(
        TRANSLATOR_PROMPT,
        f"MAP:\n{map_summary}\n\nHISTORY:\n{history_summary}\n\n"
        f"Write the three-level docs.",
        max_turns=4,
        progress_cb=_cb("translator"),
    )
    docs_summary = docs_output[-4000:] if len(docs_output) > 4000 else docs_output

    print("\n=== Synthesising into final wiki (Sonnet for polish) ===")
    if progress_cb:
        progress_cb({"type": "stage", "stage": "synthesis"})
    final_md = run_agent_with_role(
        SYNTHESIS_PROMPT,
        f"MAP:\n{map_summary}\n\nHISTORY:\n{history_summary}\n\nDOCS:\n{docs_summary}\n\n"
        f"Produce the final wiki Markdown.",
        max_turns=6,
        model=SYNTHESIS_MODEL,
        max_tokens=8192,
        progress_cb=_cb("synthesis"),
    )

    return final_md


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
    import re
    sections = re.split(r'\n(?=## )', wiki)
    for section in sections:
        heading = section.split('\n', 1)[0].strip('# ').strip()
        if not heading:
            heading = "Introduction"
        save_doc(repo_url, heading, section.strip())
        print(f"  saved: {heading}")
    print("Done — searchable via mongo_store.search_docs()")