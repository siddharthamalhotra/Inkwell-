import os, json, boto3
from datetime import datetime, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

_mongo = MongoClient(os.environ["MONGODB_URI"])
_collection = _mongo[os.environ["MONGODB_DB"]][os.environ["MONGODB_COLLECTION"]]
_bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _embed(text: str) -> list[float]:
    response = _bedrock.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text[:8000]})
    )
    return json.loads(response["body"].read())["embedding"]


def save_doc(repo_url: str, section: str, text: str) -> None:
    """Embed and persist one section."""
    _collection.insert_one({
        "repo_url": repo_url,
        "section": section,
        "text": text,
        "embedding": _embed(text),
        "created_at": datetime.now(timezone.utc),
    })


def search_docs(repo_url: str, query: str, limit: int = 5) -> list[dict]:
    """Hybrid search via $rankFusion."""
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
                                }
                            },
                            {"$match": {"repo_url": repo_url}},
                        ],
                        "textPipeline": [
                            {
                                "$search": {
                                    "index": "docs_text_index",
                                    "text": {"query": query, "path": "text"},
                                }
                            },
                            {"$match": {"repo_url": repo_url}},
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
    return list(_collection.aggregate(pipeline))


if __name__ == "__main__":
    import time

    test_repo = "https://github.com/test/repo"

    if _collection.count_documents({"repo_url": test_repo}, limit=1) == 0:
        save_doc(test_repo, "Architecture", "FastAPI app with SQLAlchemy ORM, Postgres backend, deployed on Lambda")
        save_doc(test_repo, "Auth", "OAuth2 with JWT tokens, bcrypt password hashing, session middleware")
        save_doc(test_repo, "Onboarding", "Run `make dev` to start, env vars in .env.example, hot reload enabled")
        print("Saved 3 docs. Waiting 5s for Atlas Search index sync...")
        time.sleep(5)
    else:
        print("Test docs already exist, skipping insert.")

    print("Searching...")
    results = search_docs(test_repo, "where is auth handled?")
    for r in results:
        print(f"  -> {r['section']}: {r['text'][:80]}")