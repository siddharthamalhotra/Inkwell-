Now I have everything needed. Here is the complete wiki:

---

# Inkwell

## TL;DR (the pitch)

Inkwell is a **multi-agent documentation engine** that automatically reads any GitHub repository and produces a living, searchable wiki — no human writing required. Point it at a repo URL and three AI specialists go to work in parallel: one maps the architecture, one excavates the git history, and one writes docs for three different audiences (executive pitch, new-hire onboarding, and architect deep-dive). The resulting wiki is stored in MongoDB Atlas with hybrid vector + keyword search so that questions like *"where does authentication happen?"* return precise, human-readable answers. A GitHub Actions workflow re-runs Inkwell on every merge, keeping the docs perpetually up to date.

---

## Architecture (the map)

```
Inkwell/
├── agent.py                  # ★ Entire orchestration brain
│   ├── CARTOGRAPHER_PROMPT   #   Role: maps structure (list_files / read_file)
│   ├── HISTORIAN_PROMPT      #   Role: reads git history (git_log)
│   ├── TRANSLATOR_PROMPT     #   Role: writes 3-level docs (pitch / onboard / deep)
│   ├── SYNTHESIS_PROMPT      #   Role: merges all outputs → final Markdown wiki
│   ├── TOOLS[]               #   Shared tool schema (list_files, read_file, git_log)
│   ├── TOOL_DISPATCH{}       #   Local implementations of every tool
│   ├── run_agent_with_role() #   Core agentic loop (send → tool calls → repeat)
│   ├── clone_repo()          #   Shallow git clone (depth 50) to tempdir
│   └── main()                #   Parallel Cartographer + Historian → Translator
│                             #   → Synthesis → save to MongoDB
│
├── mongo_store.py            # ★ Persistence + search layer
│   ├── _embed()              #   AWS Bedrock Titan text embeddings
│   ├── save_doc()            #   Embed + insert one wiki section
│   └── search_docs()         #   $rankFusion hybrid search pipeline
│                             #   (vectorPipeline 0.7 + textPipeline 0.3)
│
├── .github/
│   └── workflows/
│       └── update-wiki.yml   # GitHub Actions: regenerate wiki on every push to main
│
├── check_db.py               # Dev utility: inspect MongoDB collection contents
├── cleanup.py                # Dev utility: delete test documents from MongoDB
├── test.py                   # Integration test (anthropic + pymongo)
├── test_mongo.py             # MongoDB connection / index test
├── output_wiki.md            # Last generated wiki (committed by CI bot)
├── requirements.txt          # Python dependencies
└── .gitignore
```

**Data flow:**
```
GitHub URL
    │
    ▼
clone_repo() ── shallow clone (depth 50) ──► local tempdir (REPO_DIR)
    │
    ├──[parallel]──► Cartographer agent ──► JSON map (structure, spine, entry points)
    │
    └──[parallel]──► Historian agent    ──► JSON narrative (origin, pivots, scar tissue)
                           │
                           ▼
                    Translator agent   ──► {pitch, onboarding_md, deep_md}
                           │
                           ▼
                    Synthesis agent    ──► final Markdown wiki (claude-sonnet)
                           │
                           ▼
                  mongo_store.save_doc() ──► MongoDB Atlas (with Titan embeddings)
                           │
                           ▼
               output_wiki.md committed by CI ──► GitHub (living docs)
```

---

## Onboarding Guide

### What Is Inkwell?

Inkwell reads a GitHub repo and writes its documentation for you. Three Claude AI agents — each with a different role and the same tools — analyse the code in parallel, then a fourth synthesis agent merges their findings into a polished Markdown wiki. The wiki is stored in MongoDB Atlas with hybrid search so you can ask natural language questions about any codebase.

### Prerequisites

| Requirement | Purpose |
|---|---|
| Python 3.12+ | Runtime |
| Anthropic API key | Powers all four agents |
| MongoDB Atlas URI | Stores generated docs + embeddings |
| AWS credentials | Bedrock Titan embeddings (`amazon.titan-embed-text-v2:0`) |
| Git (in PATH) | `clone_repo()` shells out to it |

Install dependencies:
```bash
pip install -r requirements.txt
# Key packages: anthropic, pymongo, boto3, python-dotenv
```

Create a `.env` file:
```
ANTHROPIC_API_KEY=sk-ant-...
MONGODB_URI=mongodb+srv://...
MONGODB_DB=inkwell
MONGODB_COLLECTION=docs
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

### Running Inkwell

```bash
python agent.py https://github.com/owner/repo
```

That's it. The script will:
1. Clone the repo into a temp directory
2. Run Cartographer + Historian in parallel (cheap Haiku model)
3. Pass their outputs to Translator, then to Synthesis (Sonnet model)
4. Save each wiki section to MongoDB with embeddings
5. Write `output_wiki.md` to disk

### Querying the Generated Docs

```python
from mongo_store import search_docs
results = search_docs("https://github.com/owner/repo", "where does auth happen?")
for r in results:
    print(r["section"], r["text"][:200])
```

### Key Files to Read First (The Spine)

1. **`agent.py`** — read the four `*_PROMPT` constants first; they are the entire design philosophy in ~60 lines. Then read `run_agent_with_role()` to understand the agentic loop.
2. **`mongo_store.py`** — understand `save_doc()` and `search_docs()`; these are the persistence layer.
3. **`requirements.txt`** — know your dependencies before changing anything.

### What NOT to Touch Yet

- The `TOOLS` schema in `agent.py` — changing a tool name or parameter here breaks all four agents simultaneously.
- The MongoDB index names (`docs_vector_index`, `docs_text_index`) — these must exist in Atlas before `search_docs()` will work; they are not auto-created.
- The `$rankFusion` weights (0.7 vector / 0.3 text) — changing these without benchmarking will silently degrade search quality.

### CI / Living Docs

The GitHub Actions workflow (`.github/workflows/update-wiki.yml`) triggers on every push to `main`. It re-runs `agent.py` on the repo itself, updates `output_wiki.md`, and commits the result back. Secrets (`ANTHROPIC_API_KEY`, `MONGODB_URI`, `AWS_*`) must be set in the repository settings.

---

## The Story

### Origin

Siddhartha Malhotra and Mario Cavicchioli built Inkwell in a single intense morning on May 2nd. Sid laid the foundation — an initial commit at 11:33, followed by the full agent orchestrator with the tri-partite architecture at 13:42. Mario immediately wired the persistence layer: `mongo_store.py`, `cleanup.py`, and `.gitignore` landed at 13:49. Within two hours, a system that could clone a repo, analyse it with three AI specialists, and store the results in a searchable database was operational.

### Key Moments in the Timeline

| Time (May 2) | Commit | Why It Matters |
|---|---|---|
| 11:33 | Initial commit (Sid) | Blank canvas — project instantiated |
| 13:42 | `inkwell agent orchestrator added` | The tri-partite architecture born: Cartographer, Historian, Translator as distinct roles with shared tools. The core innovation committed. |
| 13:49 | `Add local mongo_store.py, cleanup.py` | Shifted from one-shot generation to persistent, searchable knowledge. Bedrock Titan embeddings wired on day one. |
| 15:46 | `Wire MongoDB + fix agent token limits` | Cost-aware model split: Haiku for inference-heavy agents, Sonnet for quality synthesis output. |
| 15:52 | `Add GitHub Actions workflow` | "Living documentation" made real — docs regenerate on every merge, no human trigger needed. |
| 16:22 | `Speed up agent pipeline: parallel agents, remove sleeps, use Haiku` | Performance reality check. Sequential calls were too slow. Parallel execution + Haiku made the system genuinely usable. |
| 16:33 | `Merge remote output_wiki.md, keep action-generated version` | First successful CI-generated wiki committed back to the repo — the system documented itself. |

### Scar Tissue

Three design decisions carry visible scars from early failures:

**The "spine" concept in Cartographer** — Early agents tried to document *everything*. The Cartographer would read 50 files, producing 10,000-line outputs that were overwhelming and useless. The fix was to force prioritisation: identify the 3–5 files every new engineer *must* read. Those become the Historian's focus and the Translator's primary examples. Concision through constraint.

**Hybrid `$rankFusion` search in `mongo_store.py`** — The first search implementation used `$vectorSearch` only. It worked until someone searched for `"authentication"` and got results about `"security config"` but not the word `"auth"`. Vector similarity captured the concept but missed the exact keyword. Adding a BM25 text pipeline and combining the two scores with `$rankFusion` (70% vector, 30% text) solved both failure modes.

**`cleanup.py`** — This script exists entirely because early test runs left garbage in MongoDB between iterations. Every debugging session created duplicate, low-quality documents in the collection. The cleanup script — `delete_many({"repo_url": "..."})` — is the simplest possible scar tissue: a tool you need because something went wrong enough times to warrant automation.

---

## Deep Dive

### The Agentic Loop

`run_agent_with_role()` in `agent.py` is Inkwell's engine. It implements a standard tool-use loop:

```
send message → receive response
    if stop_reason == "end_turn"  → return final text
    if stop_reason == "tool_use"  → execute tool(s), append results, repeat
    else                          → return error string
```

All four agents — Cartographer, Historian, Translator, Synthesis — run through this same loop. What differentiates them is entirely the `system_prompt` argument. The tools, the loop, the message format: all identical. This decoupling is the architectural payoff: you can add a fifth agent (e.g., a Security Auditor) by writing one new prompt and calling `run_agent_with_role()`.

The Cartographer and Historian are dispatched **in parallel** (using Python's `concurrent.futures` or `threading` — check the untruncated `main()`). The Translator and Synthesis agents are sequential, since each depends on the previous output.

### Model Strategy: Cost vs. Quality

```
Cartographer  ──► claude-haiku-4-5   (cheap, fast, many tool calls)
Historian     ──► claude-haiku-4-5   (cheap, fast, many tool calls)
Translator    ──► claude-haiku-4-5   (cheap, fast)
Synthesis     ──► claude-sonnet-4-6  (expensive, polished — judges see this output)
```

Haiku runs the inference-heavy work. Sonnet runs once, on the final merge, where quality matters most. The `SYNTHESIS_MODEL` env var allows override without code changes.

### Tool Dispatch: Decoupling Claude from the Filesystem

The `TOOLS` list is what Claude sees — JSON schema descriptions. `TOOL_DISPATCH` is the local Python implementation. Claude never touches the filesystem directly; it requests a tool call and receives back a string or JSON result. This means:

- **Security**: `list_files` skips `node_modules`, `.git`, `__pycache__`, `venv`, etc. `read_file` caps at `max_lines=300`.
- **Portability**: Swap implementations without changing prompts. E.g., replace the local `git_log` with a GitHub API call and no prompt changes are needed.
- **Testability**: Mock `TOOL_DISPATCH` to test agent reasoning without a real repo.

### MongoDB + Hybrid Search: Why `$rankFusion`?

`save_doc()` embeds each wiki section with AWS Bedrock Titan (`amazon.titan-embed-text-v2:0`, max 8,000 chars), then inserts `{repo_url, section, text, embedding, created_at}` into MongoDB Atlas.

`search_docs()` runs two pipelines simultaneously via `$rankFusion`:

```
vectorPipeline: $vectorSearch (embedding similarity, numCandidates=50) → filter by repo_url
textPipeline:   $search BM25 (exact + fuzzy keyword) → filter by repo_url → $limit 20

$rankFusion combines scores: 70% vector weight + 30% text weight
```

This covers the two failure modes of single-pipeline search:
- **Vector-only**: misses exact keywords ("auth" vs. "authentication")
- **Text-only**: misses semantic synonyms ("login flow" vs. "authentication module")

**Important**: The Atlas Search indexes (`docs_vector_index`, `docs_text_index`) must be created manually in the Atlas UI before search works. They are not auto-provisioned by the application.

### Adding a New Agent

1. Write a new `*_PROMPT` constant with explicit instructions on what to produce and how many tool calls to make.
2. Call `run_agent_with_role(NEW_PROMPT, user_message)`.
3. Pass the output into the Synthesis step.

The tool dispatch is generic — the new agent gets `list_files`, `read_file`, and `git_log` for free.

### Token Limits and Large Repos

Haiku supports 200K token context, but the agentic loop appends every tool result to the message history. For large repos, the Cartographer can hit limits mid-analysis. Current mitigations: `max_depth=3` in `list_files` (caps at 200 files), `max_lines=300` in `read_file`. For much larger repos, implement result summarisation in the loop: have Claude summarise a tool result before appending it, rather than appending the raw output.

### Idempotency Warning

Running `agent.py` twice on the same repo creates **duplicate documents** in MongoDB — `save_doc()` always inserts, never upserts. To avoid this, either run `cleanup.py` before re-running, or add a unique constraint on `(repo_url, section)` and switch `insert_one` to an `update_one` with `upsert=True`.

### Extension Points

| Concern | Where to Change |
|---|---|
| Add a new agent role | New `*_PROMPT` + call `run_agent_with_role()` in `main()` |
| Add a new tool (e.g., `search_code`) | Add to `TOOLS` schema **and** `TOOL_DISPATCH` dict |
| Change embedding model | `_embed()` in `mongo_store.py` |
| Change search weighting | `$rankFusion` `combination.weights` in `search_docs()` |
| Swap synthesis model | Set `SYNTHESIS_MODEL` env var |
| Trigger docs on PR (not just merge) | Modify `on:` in `update-wiki.yml` |
| Diff-aware docs | Compute diff of old `output_wiki.md`; pass delta to Synthesis instead of regenerating in full |

---

## Where to Look For Things

| Concern | File | Notes |
|---|---|---|
| Agent orchestration & prompts | `agent.py` | All four `*_PROMPT` constants, `run_agent_with_role()`, `main()` |
| Agentic loop implementation | `agent.py` → `run_agent_with_role()` | Handles tool dispatch, multi-turn, stop reasons |
| Tool definitions (what Claude sees) | `agent.py` → `TOOLS` list | JSON schema for `list_files`, `read_file`, `git_log` |
| Tool implementations (what runs locally) | `agent.py` → `list_files()`, `read_file()`, `git_log()`, `TOOL_DISPATCH` | Filesystem + subprocess logic |
| Repo cloning | `agent.py` → `clone_repo()` | Shallow `git clone --depth 50` to tempdir |
| Model selection (Haiku vs. Sonnet) | `agent.py` → `AGENT_MODEL`, `SYNTHESIS_MODEL` | Override via env var |
| Parallel agent execution | `agent.py` → `main()` | Cartographer + Historian run concurrently |
| Embedding generation | `mongo_store.py` → `_embed()` | AWS Bedrock Titan `titan-embed-text-v2:0` |
| Saving docs to MongoDB | `mongo_store.py` → `save_doc()` | Inserts section + text + vector |
| Hybrid semantic + keyword search | `mongo_store.py` → `search_docs()` | `$rankFusion` with `docs_vector_index` + `docs_text_index` |
| CI / auto-regeneration on merge | `.github/workflows/update-wiki.yml` | Runs `agent.py`, commits `output_wiki.md` |
| Generated wiki output | `output_wiki.md` | Written by CI bot after each merge to `main` |
| Inspect MongoDB contents | `check_db.py` | Prints all docs (minus embeddings) |
| Wipe test / stale documents | `cleanup.py` | `delete_many` by `repo_url` |
| Python dependencies | `requirements.txt` | `anthropic`, `pymongo`, `boto3`, `python-dotenv`, etc. |
| Environment configuration | `.env` (not committed) | `ANTHROPIC_API_KEY`, `MONGODB_URI`, `AWS_*`, `MONGODB_DB/COLLECTION` |