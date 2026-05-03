# ✒ Inkwell

**Multi-agent living documentation for any codebase.**

Paste a GitHub repo URL → three specialist AI agents read the code and git history → get a structured wiki you can read, download, and have a conversation with.

---

## How it works

Three agents run in a pipeline:

```
Cartographer ──┐
               ├──▶ Synthesis ──▶ Wiki
Historian    ──┘
```

| Agent | What it does |
|---|---|
| **Cartographer** | Maps architecture — entry points, core modules, dependency shape |
| **Historian** | Reads git history to explain *why* code exists, not just what it does |
| **Synthesis** | Writes the pitch, onboarding guide, and deep dive, then assembles the final wiki |

Cartographer and Historian run in parallel. Synthesis runs on Claude Sonnet and streams the wiki to the UI word-by-word as it writes.

After generation, wiki sections, raw file contents, and git log are stored in MongoDB Atlas. This powers both hybrid semantic + keyword search and the **Ask the codebase** chat agent.

---

## Ask the codebase

The chat interface is a full reasoning agent — not a search wrapper. It has access to:

1. **Wiki sections** — architecture summary, design decisions, origin story
2. **Raw source files** — read any file in the repo via `read_file` and `list_files`
3. **Git history** — the full commit log via `git_log`

It reasons about *why* code was written the way it was, whether it achieves its intent, and where the logic holds or breaks down. It can contradict the wiki if the actual code says otherwise. Conversation history is maintained across turns so reasoning builds on itself.

All three data sources are persisted in MongoDB, so the agent has full tool access for any repo ever generated — not just the one currently in memory.

---

## Features

- **Live pipeline UI** — watch each agent work in real time via SSE streaming
- **Progressive wiki render** — the wiki appears word-by-word as Synthesis writes it
- **Three-level docs** — 30-second pitch, onboarding guide, and deep architectural read in one wiki
- **Agentic chat** — reads actual source files and git history to reason about the codebase, not just retrieve wiki snippets
- **Conversation memory** — chat history is maintained across turns so follow-up questions build on prior answers
- **Persistent tool access** — file contents and git log stored in MongoDB so chat works for any repo ever generated
- **Download wiki** — export the full Markdown with one click
- **Hybrid search** — MongoDB `$rankFusion` combining vector (70%) and text (30%) search
- **Private repo support** — paste a GitHub personal access token for private repos
- **Auto-update webhook** — GitHub push webhook regenerates the wiki automatically when a significant commit lands; Claude Haiku classifies each push to skip formatting/typo/dep-bump commits
- **Prompt caching** — system prompts and tools are cached across agent turns to reduce latency and cost
- **Rate limiting** — 5 generations per IP per hour

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment variables

Create a `.env` file:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional — enables persistent search, chat tool access, and cross-session memory
MONGODB_URI=mongodb+srv://...
MONGODB_DB=inkwell
MONGODB_COLLECTION=docs
AWS_REGION=us-east-1          # for Amazon Titan embeddings via Bedrock

# Optional — override the synthesis model (default: claude-sonnet-4-6)
SYNTHESIS_MODEL=claude-sonnet-4-6

# Optional — HMAC secret for GitHub webhook signature verification
WEBHOOK_SECRET=your-secret-here
```

> Without MongoDB the app still runs — wiki generation works fully, and chat falls back to in-memory keyword search over the current session's wiki. Persistent tool access and vector search require MongoDB.

### 3. Run

```bash
python app.py
```

Open [http://localhost:5001](http://localhost:5001).

---

## Auto-update webhook

Inkwell can regenerate a repo's wiki automatically whenever a significant commit is pushed.

### How it works

When GitHub fires a `push` event, Inkwell runs a fast Claude Haiku call to classify the diff:

- **Regenerates** for: new features, architectural changes, significant refactors, new modules, major bug fixes, API changes
- **Skips** for: typo/comment fixes, README-only changes, dependency bumps, formatting/lint, test-only, CI config changes

If significant, wiki generation + MongoDB snapshot run in the background. GitHub gets a `202` response immediately.

### Setup

1. Generate a wiki for your repo — the webhook URL appears in the setup card below the wiki
2. Go to your repo → **Settings → Webhooks → Add webhook**
3. Set **Payload URL** to `https://your-inkwell-domain/webhook`
4. Set **Content type** to `application/json`
5. Under "Which events", choose **Just the push event**
6. Optionally generate a secret and set it in both GitHub and your `.env` as `WEBHOOK_SECRET`

> Without `WEBHOOK_SECRET` set, the endpoint accepts all requests. Set it in production to verify that payloads are genuinely from GitHub.

---

## Architecture

```
app.py          Flask web server + SSE streaming + rate limiting
agent.py        Multi-agent orchestration + agentic chat with tool access
mongo_store.py  MongoDB persistence — wiki sections, file contents, git log
index.html      Single-page UI (vanilla JS + marked.js)
scripts/        Dev utilities — check_db.py, cleanup.py, test.py, test_mongo.py
```

---

## Stack

- **Claude Haiku** — Cartographer and Historian (fast, high tool-call throughput)
- **Claude Sonnet** — Synthesis and chat (quality output, streamed)
- **MongoDB Atlas** — vector + full-text hybrid search via `$rankFusion`; file and git log persistence
- **Amazon Titan** — text embeddings via AWS Bedrock
- **Flask** — backend with Server-Sent Events for streaming
