import os, json, re
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

_MONGO_URI   = os.environ.get("MONGODB_URI")
_MONGO_DB    = os.environ.get("MONGODB_DB")
_MONGO_COLL  = os.environ.get("MONGODB_COLLECTION")
_AWS_REGION  = os.environ.get("AWS_REGION", "us-east-1")

_configured = bool(_MONGO_URI and _MONGO_DB and _MONGO_COLL)

_collection       = None  # wiki sections
_files_collection = None  # raw repo file contents
_git_collection   = None  # git log
_bedrock          = None

# In-memory fallback store — populated on every save_doc call so chat works
# even when MongoDB is not configured.
_memory: dict[str, list[dict]] = {}  # repo_url -> [{"section": str, "text": str}]


def _get_collection():
    global _collection
    if _collection is None:
        from pymongo import MongoClient
        _collection = MongoClient(_MONGO_URI)[_MONGO_DB][_MONGO_COLL]
    return _collection

def _get_files_collection():
    global _files_collection
    if _files_collection is None:
        from pymongo import MongoClient
        _files_collection = MongoClient(_MONGO_URI)[_MONGO_DB][f"{_MONGO_COLL}_files"]
    return _files_collection

def _get_git_collection():
    global _git_collection
    if _git_collection is None:
        from pymongo import MongoClient
        _git_collection = MongoClient(_MONGO_URI)[_MONGO_DB][f"{_MONGO_COLL}_git"]
    return _git_collection

def _get_bedrock():
    global _bedrock
    if _bedrock is None:
        import boto3
        _bedrock = boto3.client("bedrock-runtime", region_name=_AWS_REGION)
    return _bedrock

def _embed(text: str) -> list[float]:
    response = _get_bedrock().invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text[:8000]})
    )
    return json.loads(response["body"].read())["embedding"]


def _memory_search(repo_url: str, query: str, limit: int) -> list[dict]:
    """Keyword-scored search over the in-memory section store."""
    docs = _memory.get(repo_url, [])
    if not docs:
        return []
    words = query.lower().split()
    scored = []
    for doc in docs:
        text_lower = doc["text"].lower()
        score = sum(text_lower.count(w) for w in words)
        scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [d for score, d in scored if score > 0]
    return (results or docs)[:limit]


# ---------------------------------------------------------------------------
# Wiki sections
# ---------------------------------------------------------------------------

def save_doc(repo_url: str, section: str, text: str) -> None:
    # Always write to in-memory store
    if repo_url not in _memory:
        _memory[repo_url] = []
    existing = _memory[repo_url]
    for i, doc in enumerate(existing):
        if doc["section"] == section:
            existing[i] = {"repo_url": repo_url, "section": section, "text": text}
            break
    else:
        existing.append({"repo_url": repo_url, "section": section, "text": text})

    if not _configured:
        return
    try:
        _get_collection().update_one(
            {"repo_url": repo_url, "section": section},
            {"$set": {
                "text":       text,
                "embedding":  _embed(text),
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception:
        pass


def search_docs(repo_url: str, query: str, limit: int = 5) -> list[dict]:
    if _configured:
        try:
            query_vec = _embed(query)
            pipeline = [
                {
                    "$rankFusion": {
                        "input": {
                            "pipelines": {
                                "vectorPipeline": [
                                    {
                                        "$vectorSearch": {
                                            "index": "docs_vector_index",
                                            "path": "embedding",
                                            "queryVector": query_vec,
                                            "numCandidates": 50,
                                            "limit": 20,
                                            "filter": {"repo_url": {"$eq": repo_url}},
                                        }
                                    },
                                ],
                                "textPipeline": [
                                    {
                                        "$search": {
                                            "index": "docs_text_index",
                                            "text": {"query": query, "path": "text"},
                                        }
                                    },
                                    {"$match": {"repo_url": repo_url, "section": {"$exists": True}}},
                                    {"$limit": 20},
                                ],
                            }
                        },
                        "combination": {
                            "weights": {"vectorPipeline": 0.7, "textPipeline": 0.3}
                        },
                    }
                },
                {"$limit": limit},
                {"$project": {"_id": 0, "section": 1, "text": 1, "repo_url": 1}},
            ]
            results = list(_get_collection().aggregate(pipeline))
            if results:
                return results
        except Exception:
            pass

    return _memory_search(repo_url, query, limit)


# ---------------------------------------------------------------------------
# Repo file contents — persisted for chat tool access
# ---------------------------------------------------------------------------

def save_file(repo_url: str, path: str, content: str) -> None:
    if not _configured:
        return
    try:
        _get_files_collection().update_one(
            {"repo_url": repo_url, "path": path},
            {"$set": {"content": content, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception:
        pass


def read_file_db(repo_url: str, path: str) -> str | None:
    if not _configured:
        return None
    try:
        doc = _get_files_collection().find_one(
            {"repo_url": repo_url, "path": path}, {"content": 1}
        )
        return doc["content"] if doc else None
    except Exception:
        return None


def list_files_db(repo_url: str, subdir: str = "") -> list[str]:
    if not _configured:
        return []
    try:
        query: dict = {"repo_url": repo_url}
        if subdir:
            query["path"] = {"$regex": f"^{re.escape(subdir)}"}
        docs = _get_files_collection().find(query, {"path": 1, "_id": 0})
        return [d["path"] for d in docs]
    except Exception:
        return []


def has_repo_snapshot(repo_url: str) -> bool:
    """True if file contents have been stored for this repo."""
    if not _configured:
        return False
    try:
        return bool(_get_files_collection().find_one({"repo_url": repo_url}, {"_id": 1}))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Git log — persisted for chat tool access
# ---------------------------------------------------------------------------

def save_git_log(repo_url: str, commits: list[dict]) -> None:
    if not _configured:
        return
    try:
        _get_git_collection().update_one(
            {"repo_url": repo_url},
            {"$set": {"commits": commits, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception:
        pass


def get_git_log_db(repo_url: str, limit: int = 30) -> list[dict]:
    if not _configured:
        return []
    try:
        doc = _get_git_collection().find_one({"repo_url": repo_url}, {"commits": 1})
        return (doc.get("commits") or [])[:limit] if doc else []
    except Exception:
        return []
