# Inkwell

> *Living documentation for any codebase — auto-generated, semantically searchable, and always in sync.*

---

## TL;DR (the pitch)

Inkwell is a **multi-agent documentation system** that points at any public GitHub repo and produces a comprehensive, beautiful wiki in minutes — then makes it permanently searchable. Give it a URL; it clones the repo and simultaneously dispatches three specialist AI agents: the **Cartographer** (maps structure), the **Historian** (reads git log to explain *why* things exist), and the **Translator** (writes docs for three audiences — pitch, onboarding, deep dive). A fourth **Synthesis** agent consolidates all three outputs into a polished Markdown wiki. Every section is embedded via AWS Bedrock Titan and stored in MongoDB Atlas, enabling hybrid semantic + keyword search over your generated docs. Inkwell is for engineering teams who are tired of documentation rotting on a shelf — the wiki regenerates automatically on every merge, and you can query it the same way you'd ask a senior engineer: *"Where does authentication happen?"*

---

## Architecture (the map)

```
Inkwell/
│
├── app.py                        ← Web entrypoint (Flask). Routes: GET /, GET /generate (SSE),
│                                   POST /search. Normalises GitHub URLs, streams progress events.
│
├── agent.py                      ← Orchestration brain. Clones repo, spawns three specialist
│   │                               Claude agents in parallel, pipes outputs to Synthesis,
│   │                               returns final Markdown wiki. Also wires save/search to MongoDB.
│   │
│   ├── [Cartographer agent]      ← Reads file tree + key files → JSON structural map
│   ├── [Historian agent]         ← Reads git log → JSON origin story + scar tissue
│   ├── [Translator agent]        ← Takes map + history → pitch / onboarding / deep docs
│   └── [Synthesis agent]         ← Consolidates all three → final README-style wiki
│
├── mongo_store.py                ← Data layer. Embeds text via AWS Bedrock Titan (1536-dim),
│                                   persists to MongoDB Atlas, executes $rankFusion hybrid search
│                                   (70% vector + 30% BM25 keyword).
│
├── index.html                    ← Frontend SPA. Dark-themed, vanilla JS + Marked.js.
│                                   Form → SSE progress stream → rendered wiki → search UI.
│
├── requirements.txt              ← anthropic, pymongo, boto3, flask, python-dotenv
│
├── check_db.py                   ← Debug utility: counts docs, prints section previews.
├── cleanup.py                    ← Maintenance utility: deletes docs by repo URL.
├── test.py                       ← Integration tests
├── test_mongo.py                 ← MongoDB-specific tests
├── output_wiki.md                ← Last auto-generated wiki (committed by CI runner)
│
└── .github/
    └── workflows/
        └── update-wiki.yml       ← CI/CD: regenerates wiki + commits output_wiki.md on every
                                    push to main. Requires ANTHROPIC_API_KEY, AWS_*, MONGODB_URI
                                    in GitHub Secrets.
```

**Data flow:**
```
POST /generate?url=<github_url>
      │
      ▼
  app.py  ──clone──▶  agent.py
                          │
                 ┌────────┴────────┐
                 ▼                 ▼
           Cartographer       Historian        (parallel, claude-haiku)
                 └────────┬────────┘
                          ▼
                      Translator               (sequential, claude-haiku)
                          ▼
                       Synthesis               (claude-sonnet, polished output)
                          │
              ┌───────────┴────────────┐
              ▼                        ▼
        mongo_store.py           SSE → index.html
     (embed + persist)          (render markdown)
```

---

## Onboarding Guide

### What You Need Before You Start

| Requirement | Notes |
|---|---|
| Python 3.12+ | Tested on 3.13; `match` syntax used in places |
| `git` on PATH | Agent shells out to `git clone` and `git log` |
| Anthropic API key | Haiku for agents, Sonnet for synthesis |
| AWS credentials | Bedrock Titan for embeddings (`us-east-1` default) |
| MongoDB Atlas URI | With Atlas Search indexes configured (see below) |

### Installation

```bash
git clone https://github.com/siddharthamalhotra/Inkwell-
cd Inkwell-
pip install -r requirements.txt
```

Create a `.env` file at the root:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
SYNTHESIS_MODEL=claude-sonnet-4-6      # optional override

AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

MONGODB_URI=mongodb+srv://...
MONGODB_DB=inkwell
MONGODB_COLLECTION=docs
```

### MongoDB Atlas Setup

Before running, your Atlas cluster needs two Search indexes on the `docs` collection:

1. **`docs_vector_index`** — a Vector Search index on the `embedding` field (1536 dimensions, cosine similarity).
2. **`docs_text_index`** — a full-text Atlas Search index on the `text` field.

Without these, `mongo_store.py`'s `$rankFusion` pipeline will error.

### Running Locally

**Option A — Web UI (recommended):**
```bash
python app.py
# → http://localhost:5001
```
Paste a GitHub URL, click **Generate**, watch the SSE progress stream, read the wiki, search it.

**Option B — CLI:**
```bash
python agent.py https://github.com/owner/repo
# outputs to stdout + saves to output_wiki.md
```

**Option C — Verify DB is working:**
```bash
python check_db.py     # inspect stored docs
python cleanup.py      # delete test docs
```

### The Five Files You Must Read First

1. **`agent.py`** — start here; understand the four-agent pipeline and the `generate_wiki()` orchestrator
2. **`app.py`** — the web layer; see how SSE streaming works and how URLs are normalised
3. **`mongo_store.py`** — the persistence layer; understand `_embed()` and the `$rankFusion` pipeline
4. **`index.html`** — the UI; EventSource handling, Marked.js rendering, search form
5. **`requirements.txt`** — minimal deps, no framework magic to learn

### What NOT to Touch Yet

- **The agent system prompts** in `agent.py` — they are carefully tuned; small wording changes alter output quality significantly.
- **The `$rankFusion` weights** in `mongo_store.py` — `0.7 vector / 0.3 BM25` was calibrated empirically; changing them without testing degrades search relevance.
- **The CI workflow** — it has secrets and permission requirements that are easy to break silently (see *The Story* section).

---

## The Story

### Origin — May 2, 2026, ~13:42

Siddhartha Malhotra pushed the first meaningful commit: **"inkwell agent orchestrator added."** The core idea was already fully formed — three specialist agents with different lenses on the same codebase, a synthesis pass to unify them. This multi-perspective architecture became the DNA that everything else was built around.

### The Persistence Pivot — 13:49

Within minutes, Mario Cavicchioli added `mongo_store.py`, `cleanup.py`, and a `.gitignore`. This was the project's first major architectural decision: transform Inkwell from a one-shot CLI tool that printed Markdown and vanished into a **persistent, searchable documentation system**. Without this pivot, every wiki generation would be ephemeral.

### Stability — 15:46

`"Wire MongoDB + fix agent token limits"` — a single commit that quietly solved two production blockers. The agents were hitting token ceilings and failing silently; the database integration wasn't wired end-to-end. This is the commit that made Inkwell actually work in practice.

### The Performance Crisis — 16:22

`"Speed up agent pipeline: parallel agents, remove sleeps, use Haiku"` — by mid-afternoon the team had discovered that running agents sequentially with expensive models and artificial sleep delays made the pipeline unusably slow. The fix was threefold:

1. **Parallelise** Cartographer + Historian using `ThreadPoolExecutor`
2. **Drop sleeps** (a common Claude API rate-limit workaround that wasn't needed)
3. **Switch to `claude-haiku`** for the three specialist agents — Sonnet is reserved only for the final synthesis pass where polish matters

The result: the `AGENT_MODEL` / `SYNTHESIS_MODEL` split visible in `agent.py` today is a direct fossil of this crisis.

### The Web Layer — 16:58

Sid added `app.py` — the Flask web interface that completed the full user journey: URL in → wiki out → search. Before this, Inkwell was a developer tool; after it, it was a product.

### CI Growing Pains — 15:52–16:25

The automation story unfolded in a tight cluster of commits:

| Commit | What happened |
|---|---|
| `661b9fc` | GitHub Actions workflow added |
| `923a5f8` | "debug: add secrets verification step" — secrets weren't passing correctly |
| `fb37fc6` | "Fix workflow: add contents write permission for push" — runner couldn't commit back |
| `a23cf8a` / `412cb5c` | Auto-generated wiki commits from the now-working runner |

The `[skip ci]` tag on bot commits prevents infinite regeneration loops — already in place and essential.

---

## Deep Dive

### The Four-Agent Pipeline

Inkwell's core insight is that **documentation has multiple audiences, and no single reader sees all dimensions of a codebase simultaneously**. The solution: specialist agents with constrained prompts.

```
Cartographer  →  "What is here and how does it connect?"   (structure lens)
Historian     →  "Why does it exist and how did it evolve?" (history lens)
Translator    →  "How do I explain this to three audiences?" (communication lens)
Synthesis     →  "Make it beautiful and coherent."          (polish lens)
```

Each of the first three agents shares the **same tool set** (`list_files`, `read_file`, `git_log`) but is prompted to use them differently. The Cartographer is capped at ~10 file reads for breadth. The Historian is capped at 5–6 git tool calls for efficiency. The Translator is discouraged from reading files at all (it already has the map and history).

**Model selection is deliberate:**
- Haiku (agents): fast, cheap, high rate-limit headroom — fine for tool-calling loops
- Sonnet (synthesis): slower, more expensive, better prose — justified for the one output humans actually read

### The Persistence Layer in Detail

`mongo_store.py` stores each wiki section as:

```json
{
  "repo_url": "https://github.com/owner/repo",
  "section": "Architecture",
  "text": "...",
  "embedding": [0.023, -0.114, ...],
  "created_at": "2026-05-02T15:36:08Z"
}
```

Search uses MongoDB's `$rankFusion` with two sub-pipelines:

```python
$rankFusion: {
  input: {
    pipelines: {
      vectorPipeline: [$vectorSearch → $match],   # semantic similarity
      textPipeline:   [$search → $match → $limit] # BM25 keyword
    }
  },
  combination: {
    weights: { vectorPipeline: 0.7, textPipeline: 0.3 }
  }
}
```

This hybrid approach means a query like `"database layer"` finds both exact keyword matches *and* semantic neighbors like `"persistence module"` or `"MongoDB integration"`.

**Known scar tissue in this layer:**
- No idempotency: re-running on the same repo creates duplicate documents (no hash-based dedup)
- No transaction semantics: a mid-generation crash leaves partial sections in the DB
- Cleanup is manual via `cleanup.py` (hardcoded to test repo URL — fragile)
- Embeddings are re-computed on every run (expensive; no caching)

**Future fix:** Add an idempotency key of `hash(repo_url + commit_sha)` and upsert instead of insert.

### CI/CD: Automation and Its Scars

The workflow in `.github/workflows/update-wiki.yml` regenerates `output_wiki.md` on every push to `main` and commits it back. **Critical requirements** that burned the team during setup:

1. `contents: write` permission must be explicitly declared — GitHub Actions defaults to read-only
2. All three credential sets (`ANTHROPIC_API_KEY`, `AWS_*`, `MONGODB_URI`) must be in GitHub Secrets
3. Bot commits must include `[skip ci]` to prevent infinite trigger loops (already handled)
4. AWS Bedrock must be available in your configured region (`us-east-1` default)

### Extension Points

**Add a fourth agent:**
```python
# In agent.py, add a new system prompt + run_agent_with_role() call
SECURITY_AUDITOR_PROMPT = """You are the Security Auditor..."""

def run_security_auditor():
    return run_agent_with_role(SECURITY_AUDITOR_PROMPT, ...)
```

**Swap the embedding model:**
```python
# In mongo_store.py, replace _embed():
# Current: AWS Bedrock Titan
response = bedrock_client.invoke_model(modelId="amazon.titan-embed-text-v2:0", ...)

# Alternative: OpenAI
response = openai_client.embeddings.create(model="text-embedding-3-small", input=text)
```

**Tune hybrid search weights:**
```python
# In mongo_store.py $rankFusion combination block:
"weights": {"vectorPipeline": 0.6, "textPipeline": 0.4}  # more keyword weight
```

**Add a Validation agent** (post-synthesis pass): check for contradictions between sections, missing file references, and orphaned claims. Route failures to a human reviewer before persistence.

### Known Gotchas

| Gotcha | Detail |
|---|---|
| **Token limits** | Agents read entire files up to 300 lines. Repos >50K lines will be silently truncated. No incremental indexing. |
| **Shallow clone depth** | `git clone --depth 50` — only 50 commits of history visible to the Historian. Ancient repositories will have incomplete WHY analysis. |
| **AWS region** | Bedrock Titan is not available in all regions. If embeddings fail, check `AWS_REGION` in `.env` and your Atlas configuration. |
| **Concurrency** | Multiple simultaneous `/generate` calls share the global `REPO_DIR` variable in `agent.py` — parallel requests will corrupt each other's working directory. |
| **Private repos** | `git clone` will fail without credentials injected. No SSH/token auth flow is implemented. |
| **Markdown only** | Translator outputs GitHub Flavoured Markdown. Repos using Sphinx, JSDoc, or AsciiDoc conventions will get output in a different style than their existing docs. |

---

## Where to Look For Things

| Concern | File(s) |
|---|---|
| Web server, routes, SSE streaming | `app.py` |
| Agent prompts (Cartographer, Historian, Translator, Synthesis) | `agent.py` — `*_PROMPT` constants |
| Agent orchestration & parallelism | `agent.py` — `generate_wiki()` |
| Tool implementations (list_files, read_file, git_log) | `agent.py` — `TOOL_DISPATCH` and functions above it |
| Repo cloning logic | `agent.py` — `clone_repo()` |
| Model selection (Haiku vs Sonnet) | `agent.py` — `AGENT_MODEL`, `SYNTHESIS_MODEL` |
| Embedding generation (AWS Bedrock Titan) | `mongo_store.py` — `_embed()` |
| Storing wiki sections to MongoDB | `mongo_store.py` — `save_doc()` |
| Hybrid semantic + keyword search | `mongo_store.py` — `search_docs()` / `$rankFusion` pipeline |
| Frontend UI, SSE event handling, search form | `index.html` |
| Markdown rendering in browser | `index.html` — Marked.js integration |
| CI/CD wiki regeneration on merge | `.github/workflows/update-wiki.yml` |
| Debugging MongoDB contents | `check_db.py` |
| Deleting docs by repo URL | `cleanup.py` |
| Python dependencies | `requirements.txt` |
| Last auto-generated wiki output | `output_wiki.md` |