# Inkwell

> **Living documentation for any GitHub codebase — automatically generated, semantically searchable, and never stale.**

---

## TL;DR (the pitch)

Inkwell is an AI-powered documentation engine that reads any GitHub repository and writes a complete, structured wiki — automatically, on every merge. Four specialist Claude agents each examine the codebase through a different lens: the **Cartographer** maps the architecture, the **Historian** explains *why* the code exists through git history, the **Translator** writes docs for three audiences (pitch, onboarding, deep dive), and the **Synthesis** agent weaves it all into a single polished Markdown wiki. The output is committed back to the repo as `output_wiki.md` and simultaneously stored in MongoDB Atlas with AWS Bedrock embeddings, enabling hybrid semantic search so you can ask *"where is auth handled?"* and get a precise, ranked answer — across every wiki version, forever.

---

## Architecture (the map)

```
inkwell/
│
├── agent.py                        ← Orchestrator: runs 3 agents in parallel, synthesises output
│   ├── CARTOGRAPHER_PROMPT         ← Lens 1: structural map of the target repo
│   ├── HISTORIAN_PROMPT            ← Lens 2: git-history narrative and scar tissue
│   ├── TRANSLATOR_PROMPT           ← Lens 3: three-level docs (pitch / onboard / deep)
│   ├── SYNTHESIS_PROMPT            ← Final pass: merges all three into Markdown wiki
│   ├── run_agent_with_role()       ← Agentic loop with tool use + multi-turn conversation
│   ├── clone_repo()                ← Shallow git clone of target repo to tempdir
│   └── TOOL_DISPATCH               ← list_files | read_file | git_log
│
├── mongo_store.py                  ← Persistence + semantic search layer
│   ├── _embed()                    ← AWS Bedrock Titan (amazon.titan-embed-text-v2:0)
│   ├── save_doc()                  ← Inserts section text + embedding into MongoDB
│   └── search_docs()               ← $rankFusion pipeline (70% vector / 30% full-text)
│
├── .github/
│   └── workflows/
│       └── update-wiki.yml         ← CI trigger: runs on push to main, commits output_wiki.md
│
├── output_wiki.md                  ← Generated artifact (committed by workflow bot)
│
├── cleanup.py                      ← Dev utility: purge test docs from MongoDB by repo_url
├── check_db.py                     ← Dev utility: inspect MongoDB collection contents
│
├── test.py                         ← Smoke test: Anthropic API + MongoDB connectivity
├── test_mongo.py                   ← Integration test: insert/search cycle for mongo_store.py
├── office.html                     ← UI prototype for semantic search (Flask/fetch)
└── requirements.txt                ← anthropic, pymongo, voyageai, flask, boto3, python-dotenv, rich
```

**Dependency flow:**

```
update-wiki.yml
    └── agent.py
            ├── mongo_store.py
            │       ├── pymongo  →  MongoDB Atlas
            │       └── boto3    →  AWS Bedrock (embeddings)
            └── anthropic SDK  →  Claude Haiku (agents) / Claude Sonnet (synthesis)
```

---

## Onboarding Guide

### What You're Looking At

Inkwell has one job: keep documentation in sync with code, automatically. When someone merges a PR, a GitHub Actions workflow wakes up, clones the target repo, runs four AI agents against it, and commits a fresh wiki back — all without a human touching anything.

### The Three Files You Must Read First

| File | Why |
|---|---|
| `agent.py` | The brain. Contains all four agent prompts and the orchestration loop. |
| `mongo_store.py` | The memory. Handles embedding and hybrid search. |
| `.github/workflows/update-wiki.yml` | The heartbeat. Defines when and how the system fires. |

### Key Concepts

**Four agents, same tools, different lenses.** Every agent can call `list_files`, `read_file`, and `git_log` on the cloned target repo. What differs is the *system prompt* — the Cartographer is told to draw a map, the Historian is told to read history, the Translator is told to write for humans. Same toolbox, very different outputs.

**Parallel execution, cheap model, expensive synthesis.** The three specialist agents run concurrently (Claude Haiku — fast and cheap). Only the final Synthesis pass uses Claude Sonnet, because that's the output people actually read.

**Embeddings live in AWS Bedrock, docs live in MongoDB.** Each generated wiki section is embedded via Amazon Titan and stored as a document. The `search_docs()` function then does hybrid `$rankFusion` search scoped to a `repo_url`.

### Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up .env
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, MONGODB_URI, MONGODB_DB, MONGODB_COLLECTION,
#           AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION

# 3. Point at a repo and run
TARGET_REPO=https://github.com/your-org/your-repo.git python agent.py
# Output → output_wiki.md + MongoDB docs collection

# 4. Test the search layer
python test_mongo.py

# 5. Clean up test documents
python cleanup.py
```

### What NOT to Touch Yet

- **The `$rankFusion` pipeline weights** in `mongo_store.py` — the 70/30 split is empirically tuned; changing it affects all search quality.
- **The `TOOLS` list** in `agent.py` — adding tools affects every agent's token budget simultaneously.
- **The `[skip ci]` tag** in the workflow's commit message — removing it causes an infinite loop of wiki regenerations.

### Secrets Required (GitHub → Settings → Secrets)

| Secret | Used By |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API calls |
| `MONGODB_URI` | Atlas connection string |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Bedrock embedding calls |

---

## The Story

### Origin (May 2, 2026 — 11:33 AM)

Siddhartha Malhotra landed the initial commit with the full vision already clear: three specialist agents, each with a different prompt but the same tools. The foundational insight was deceptively simple — *different lenses on the same codebase, not different codebases for different agents*. That single design decision shapes everything downstream.

### The Collaboration Begins (1:42–2:00 PM)

Mario Cavicchioli merged partner code and introduced the local infrastructure — `mongo_store.py`, `cleanup.py`, `.gitignore`. What had been a solo orchestrator prototype started to grow a backbone. This is when "local experiment" began its transition toward "production system."

### Going to Production (3:46 PM)

The big wire-up: MongoDB Atlas, AWS Bedrock embeddings, and the hybrid `$rankFusion` search pipeline — all in a single commit. The 70/30 vector-to-text weighting wasn't academic; it reflects what actually worked for documentation search (semantic intent dominant, exact keyword recall supplementary). At this point, generated docs were persistent and queryable across time, not just ephemeral console output.

### The Living Documentation Promise (3:52 PM)

Six minutes later: the GitHub Actions workflow. Every merge now triggers a fresh wiki. Docs are no longer something you write and forget — they regenerate themselves. This commit is arguably the philosophical centre of the whole project.

### The Speed & Cost Crisis (4:22 PM)

Running three full agents sequentially on every merge was too slow and too expensive. The response was pragmatic and fast: parallelize the specialist agents, strip out artificial sleeps, switch from Sonnet to Haiku for the reasoning-heavy-but-cheap agent work. Sonnet is preserved only for the final synthesis — the thing a human actually reads. This tiered model strategy became a core architectural principle.

### Scar Tissue

| Artefact | What Happened |
|---|---|
| `update-wiki.yml` — "Verify secrets are set" step | Early CI runs silently failed when secrets were absent. Now they explode loudly with character-count diagnostics. Never remove this step. |
| Agent prompts — "make at most 5-6 tool calls" | Hit Claude's context window on large repos. Hard tool-call caps were added to every agent prompt after painful silent failures. |
| Amazon Titan embeddings (not Anthropic native) | A pragmatic choice based on existing AWS infrastructure. Switching later means re-embedding the entire stored corpus — a breaking migration. |

---

## Deep Dive

### The Agent Loop: How It Actually Works

Each of the four agents runs inside `run_agent_with_role()` — a standard Claude multi-turn agentic loop. The agent receives its system prompt and a user message pointing at the target repo. It then interleaves `tool_use` (calling `list_files`, `read_file`, or `git_log`) with reasoning until it reaches `end_turn` and emits its structured JSON output. The three specialist agents run concurrently via Python threading or `asyncio` (parallelized in the May 2 speed commit). Their outputs are collected and fed as a single combined user message to the Synthesis agent, which produces the final Markdown using Claude Sonnet.

### Why Amazon Titan Embeddings?

This was a **team infrastructure decision**, not a technical requirement. AWS Bedrock access was already provisioned; reusing it avoided a new vendor relationship and kept embeddings server-side (no data leaves the AWS boundary). The cost is lock-in: switching to Anthropic or Voyage embeddings later requires re-embedding every document already stored in MongoDB — a full corpus migration with no shortcut. If you're considering this, document the decision *before* you accumulate thousands of stored docs.

### Hybrid Search: The 70/30 Split Explained

The `$rankFusion` pipeline in `mongo_store.py` combines two sub-pipelines:

- **Vector search (70%):** Semantic similarity via Titan embeddings — finds docs about "authentication" even if the word "auth" never appears.
- **Full-text search (30%):** Atlas Search — rewards exact keyword hits like `ANTHROPIC_API_KEY` or `$rankFusion`.

Both pipelines filter by `repo_url`, so search is always scoped to a single repo's history. The 70/30 weight is tunable around line ~40 of `mongo_store.py`. Repos heavy on domain jargon or acronyms may benefit from shifting toward full-text.

### Token Budget: A Hard Lesson Baked into the Prompts

Every agent prompt contains explicit frugality instructions because the team hit Claude's context window on large repos — silently, with no error, just truncated output. The resulting constraints:

- Cartographer: *"Don't read more than ~10 files"*
- Historian: *"Make at most 5-6 tool calls total"*
- Translator: *"Only fetch a file if you need to verify a specific claim"*
- Synthesis: explicit output size limit

**If you add a new agent or expand tool access, test on a 2000+ file repo first.** Context exhaustion is silent and hard to debug after the fact.

### The Secrets Validation Step: Don't Delete It

The `update-wiki.yml` step that prints secret character counts is pure scar tissue from early deployments. When `ANTHROPIC_API_KEY` or `MONGODB_URI` were absent, the workflow failed 3+ minutes into execution with a cryptic error. The validation step costs 2 seconds and surfaces the problem in the first 10 lines of CI output. It stays.

### Extension Points

**Adding a new specialist agent** (e.g., a "Security Auditor"):
1. Write a new `*_PROMPT` constant in `agent.py`
2. Add it to the `agents_and_prompts` dict
3. The orchestrator will automatically parallelize it and pass its output to Synthesis

**Changing the output format** (HTML, Jupyter, etc.):
1. Modify the Synthesis prompt to target your format
2. Update the write path in `agent.py` (currently hardcoded to `output_wiki.md`)
3. Update the `git add` line in the workflow

**Building a chat interface:**
`search_docs(repo_url, query)` in `mongo_store.py` is the ready-made entry point. Wrap it in a Flask route and you have semantic search over all generated docs. See `office.html` for a prototype UI.

### The Automation Cost Model

Every merge to `main` costs approximately:
- **~20 Claude API calls** (Haiku × 3 agents × 5–6 tool calls + Sonnet × 1 synthesis)
- **~20 Bedrock embedding calls** (one per stored section)
- **30–60 seconds** of wall-clock time (parallelized)
- **Cents per run** at current pricing

The trade: constant low-grade cost per merge, zero ongoing maintenance burden, and a semantically searchable archive of every documentation state your codebase has ever been in.

### Known Gotchas

1. **Binary files** (PDFs, ZIPs) — agents may attempt to `read_file` them and get garbled output. Add them to `.gitignore` or the `SKIP_DIRS` set in `agent.py`.
2. **Large git histories** — `git_log` defaults to `--limit 30`. Repos with 50+ commits/day will present a misleading slice of history to the Historian. Consider increasing the limit or passing specific paths.
3. **Private sub-repos** — the target repo must be reachable from the GitHub Actions runner. Add SSH deploy keys to the workflow for private dependencies.
4. **MongoDB connection pooling** — `MongoClient` is module-level global in `mongo_store.py`. At current parallelism this is fine; if you scale to many concurrent runs, connection exhaustion becomes a risk.

---

## Where to Look For Things

| Concern | File(s) |
|---|---|
| Agent prompts & personas | `agent.py` — `CARTOGRAPHER_PROMPT`, `HISTORIAN_PROMPT`, `TRANSLATOR_PROMPT`, `SYNTHESIS_PROMPT` |
| Agent orchestration loop | `agent.py` — `run_agent_with_role()` |
| Tool implementations (file/git access) | `agent.py` — `list_files()`, `read_file()`, `git_log()`, `TOOL_DISPATCH` |
| Repo cloning | `agent.py` — `clone_repo()` |
| Embedding generation | `mongo_store.py` — `_embed()` |
| Storing a wiki section | `mongo_store.py` — `save_doc()` |
| Semantic search over docs | `mongo_store.py` — `search_docs()` |
| Hybrid search pipeline ($rankFusion) | `mongo_store.py` — aggregation pipeline in `search_docs()` |
| CI/CD trigger & automation | `.github/workflows/update-wiki.yml` |
| Secrets validation | `.github/workflows/update-wiki.yml` — "Verify secrets are set" step |
| Generated wiki output | `output_wiki.md` (committed by workflow bot) |
| Dev: purge test DB documents | `cleanup.py` |
| Dev: inspect MongoDB contents | `check_db.py` |
| API + DB smoke test | `test.py` |
| Full mongo insert/search integration test | `test_mongo.py` |
| Search UI prototype | `office.html` |
| Python dependencies | `requirements.txt` |