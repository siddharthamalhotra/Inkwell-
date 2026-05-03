# Inkwell

## TL;DR

Inkwell is a multi-agent documentation system that turns any GitHub repository into a living, searchable wiki — automatically. Three specialized AI agents (Cartographer, Historian, and Synthesis) run in parallel to map a codebase's architecture, mine its git history, and weave both into polished Markdown documentation with onboarding guides, deep dives, and architectural analysis. The result is stored in MongoDB, rendered in a single-page web app, and made queryable through hybrid semantic + full-text search and an interactive agentic chat interface. Built for developers who need to onboard fast or understand an unfamiliar codebase without reading every file.

---

## Architecture

```
inkwell/
├── app.py              # Flask web server — routes, SSE streaming, rate limiting (~200 lines)
├── agent.py            # All agent logic — Cartographer, Historian, Synthesis, agentic chat (~600 lines)
├── mongo_store.py      # MongoDB persistence, hybrid search, Bedrock embeddings, fallback store (~250 lines)
└── index.html          # Vanilla JS SPA — SSE handling, marked.js rendering, search & chat UI (~500 lines)
```

### Agent Pipeline

```
GitHub URL
  └─► clone_repo (shallow, --depth 20)
        ├─► [parallel] run_cartographer()   →  JSON architectural map
        └─► [parallel] run_historian()      →  JSON git narrative
                ↓ (both complete)
        run_synthesis()  →  streamed Markdown wiki
                ↓
        save_doc()  →  MongoDB (sections + embeddings + raw files + git logs)
                ↓
        UI renders progressively
        └─► /chat  →  agentic chat with live repo tool access
```

### Key Component Relationships

| Layer | Component | Responsibility |
|---|---|---|
| Ingestion | `clone_repo` in `agent.py` | Shallow-clones repo, scopes tools to that directory |
| Analysis | Cartographer (Claude Haiku) | Structure, files, dependencies |
| Analysis | Historian (Claude Haiku) | Git log, commit narrative, pivots |
| Synthesis | Synthesis agent (Claude Sonnet) | Merge both inputs into final wiki |
| Persistence | `mongo_store.py` | Sections, embeddings, file contents, git logs |
| Search | `$rankFusion` (MongoDB) | 70% semantic + 30% full-text |
| Chat | `agent.py` `/chat` route | Multi-turn reasoning over stored wiki + live repo tools |

---

## Onboarding Guide

**Welcome. Here's how to navigate this codebase in five minutes.**

### The Spine Files

There are four files. That's the entire backend+frontend. Start here:

1. **`agent.py`** — This is the brain. Everything about how agents think, loop, dispatch tools, and generate wikis lives here. When you want to understand *what Inkwell does*, read `agent.py`. Pay attention to `_make_tool_dispatch(repo_dir)` — it creates closures scoped to a cloned repo so tools can't escape their sandbox. The multi-turn agent loop pattern repeats for all three agents.

2. **`app.py`** — The thin web layer. Flask routes, SSE streaming setup, rate limiting (5 generations/IP/hour), and repo cache (`_repo_cache`, 1-hour TTL). Don't look here for business logic — it delegates immediately to `agent.py`.

3. **`mongo_store.py`** — Persistence and search. The most operationally interesting file. Read `save_doc()` to understand how wiki sections are stored, and `search_docs()` to understand `$rankFusion`. There is an in-memory `_memory` dict fallback — if MongoDB is down, the system still works.

4. **`index.html`** — A self-contained SPA. Handles SSE event streams from the server, renders Markdown via `marked.js`, and wires up the search and chat UI. No build step, no framework.

### Key Concepts to Internalize

- **Tool Dispatch**: Every agent gets a set of tools (`list_files`, `read_file`, `git_log`) scoped to one cloned repo via closures. No globals.
- **Prompt Caching**: System prompts use `cache_control: {"type": "ephemeral"}` — this is a Claude API feature that reduces cost and latency across multi-turn loops. Don't remove it.
- **SSE Streaming**: Wiki text streams chunk-by-chunk from Synthesis. The frontend listens for named events and appends progressively.
- **Parallel Execution**: Cartographer and Historian use `ThreadPoolExecutor` and run at the same time. Synthesis waits for both via `Future.result()`.

### What NOT to Touch Yet

- The `$rankFusion` aggregation pipeline in `mongo_store.py` — it's finely tuned; the 70/30 semantic/full-text split is deliberate.
- Agent system prompts in `agent.py` — they were carefully compressed after hitting Claude's token limits. Adding verbosity will break things.
- The SSE event format — `index.html` parses specific named event types; changing the server-side format without updating the client breaks rendering.

---

## The Story

Inkwell was created by Siddhartha Malhotra in early May 2026, conceived in a burst of activity over roughly 36 hours.

**May 2, 13:42 — The vision arrives whole.** The initial commit established the three-agent pipeline immediately. There was no "let's start with one LLM and see" phase — the architecture was born with specialization and parallelism as first principles. Cartographer maps structure. Historian mines history. Synthesis narrates. This division of labor was the founding idea.

**May 2, 13:46–15:46 — The database becomes non-negotiable.** Within hours of the first commit, MongoDB Atlas was wired in and token limit fixes were applied. The agents were hitting context walls, and git history was too large to re-fetch on every run. The solution: persist everything in MongoDB. Git logs, file contents, wiki sections — all stored so agents don't have to re-derive what they've already learned.

**May 2, 16:22 — Speed becomes a hard requirement.** Early runs were sequential with deliberate pauses. Once the concept was validated, a performance overhaul parallelized the agents, removed the sleeps, and switched from a larger model to Claude Haiku for the analysis agents. This was an explicit cost-latency tradeoff: Haiku runs cheaper and faster; Sonnet is reserved for the final synthesis where quality matters most.

**May 2, 16:58 — Proof of concept becomes product.** With the pipeline stable, a web UI shipped. The system crossed the line from internal tool to something a user could actually interact with.

**May 3, 02:49 — Batch to interactive.** The biggest pivot: agentic chat was added alongside repo snapshots. Inkwell stopped being a one-shot documentation generator and became a persistent reasoning environment. Users could now ask follow-up questions, and the chat agent could reach back into the stored repo with live tool access to answer them. Repo snapshots meant re-analysis no longer required re-cloning.

---

## Deep Dive

### Why Three Agents Instead of One?

The single-LLM approach to code summarization has a well-known failure mode: it treats a codebase as a flat document rather than a multi-dimensional artifact. Architecture (what files exist, how they connect) and history (why things are the way they are) require different reading strategies. A single prompt asking "explain this repo" gets an average of both and excels at neither.

Inkwell's answer is specialization. The Cartographer is prompted to think spatially — file trees, dependencies, data flows. The Historian is prompted to think temporally — commit messages, refactors, pivots. The Synthesis agent never sees raw files; it only sees the structured outputs of the other two, which forces it to operate at the narrative level rather than getting lost in implementation details.

### The Token Limit Scars

The most consequential architectural decision is invisible: git history is stored in MongoDB on first analysis and retrieved from there on subsequent runs, rather than fetched live each time. This is a direct response to early token exhaustion. Large repos have thousands of commits; feeding raw `git log` output into every agent turn is a fast way to hit context limits. The `save_git_log` / `get_git_log_db` pattern in `agent.py` is scar tissue from that lesson.

Similarly, agent system prompts are unusually terse for documentation-generating prompts. The compression is intentional — verbose system prompts amplified the token problem across multi-turn loops. Every word in those prompts survived a cost-benefit cut.

### Prompt Caching as Infrastructure

`cache_control: {"type": "ephemeral"}` on system prompts isn't a minor optimization — it's load-bearing. Each agent runs in a multi-turn loop (Cartographer up to ~8 turns, Historian ~6). Without caching, the system prompt is billed as input tokens on every turn. With caching, it's billed once. At scale, this is the difference between an economically viable product and one that burns tokens on boilerplate.

### The Fallback Store Pattern

`mongo_store.py` contains both MongoDB logic and an in-memory `_memory` dict that mirrors the MongoDB interface. This isn't an accident or dead code — it's a production reliability decision. If MongoDB is unavailable (connection failure, cold start, local dev without Atlas), the system degrades gracefully rather than crashing. Search quality degrades (keyword matching instead of vector similarity), but the core generation and chat flows continue to work.

### Hybrid Search Tuning

The `$rankFusion` search weights (70% semantic, 30% full-text) reflect a specific tradeoff for code documentation queries. Pure semantic search struggles with exact identifier names — class names, function names, file paths. Pure full-text search misses conceptual queries ("how does authentication work"). The 70/30 split favors conceptual understanding while keeping exact-match queries functional. This is a parameter worth tuning if recall on identifier-specific queries is poor.

### Extension Points

- **New agents**: The agent loop pattern in `agent.py` is factored cleanly. A fourth agent (e.g., a Security Auditor or Dependency Analyst) can be added by defining a new system prompt, running it in the `ThreadPoolExecutor` alongside Cartographer and Historian, and passing its JSON output to Synthesis.
- **New tools**: `_make_tool_dispatch(repo_dir)` returns a dict mapping tool names to callables. Adding a tool (e.g., `run_tests`, `grep_code`) means adding an entry to that dict and declaring it in the agent's tool schema.
- **Search weights**: The 70/30 semantic/full-text ratio is a single constant in `mongo_store.py`. It is not derived from any ML process — it can be changed directly.

---

## Where to Look For Things

| Concern | File | What to Read |
|---|---|---|
| Flask routes & SSE streaming | `app.py` | All route handlers; `Response` with `text/event-stream` |
| Rate limiting logic | `app.py` | `_rate_store` dict and IP-based check |
| Repo cloning & caching | `app.py` / `agent.py` | `clone_repo()`, `_repo_cache` |
| Agent loop (multi-turn) | `agent.py` | `run_cartographer()`, `run_historian()` |
| Parallel agent execution | `agent.py` | `ThreadPoolExecutor` block in wiki generation |
| Tool dispatch (scoped) | `agent.py` | `_make_tool_dispatch(repo_dir)` |
| Synthesis + streaming | `agent.py` | `run_synthesis()` with streamed Sonnet call |
| Agentic chat | `agent.py` | `/chat` handler and its agent loop |
| MongoDB persistence | `mongo_store.py` | `save_doc()`, `get_doc()` |
| Hybrid search | `mongo_store.py` | `search_docs()` with `$rankFusion` |
| In-memory fallback | `mongo_store.py` | `_memory` dict and its access patterns |
| Bedrock embeddings | `mongo_store.py` | Embedding generation calls |
| Git log persistence | `agent.py` + `mongo_store.py` | `save_git_log()`, `get_git_log_db()` |
| Frontend SSE handling | `index.html` | Event listener setup and progressive rendering |
| Markdown rendering | `index.html` | `marked.js` integration |
| Search & chat UI | `index.html` | Search form, chat form, result display logic |
| Agent system prompts | `agent.py` | Constants near top of file; do not pad with verbosity |